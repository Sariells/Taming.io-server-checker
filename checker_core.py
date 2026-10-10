import os
import re
import time

from datetime import datetime

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


class ServerChecker:
    def __init__(
        self,
        region_name,
        server_count,
        screenshot_dir="screens",
        headless=False,
    ):
        self.region = region_name
        self.server_count = server_count
        self.screenshot_dir = screenshot_dir
        self.base_url = "https://taming.io/"
        self.headless = headless

        self.max_server_attempts = 3

        # Обычная загрузка страницы
        self.nav_timeout = 60000

        # Сколько максимум ждём Cloudflare / появления игры
        self.game_ready_timeout = 180000


    def log(self, msg):
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        )


    # ============================================================
    # GENERIC CLICK / CHECK HELPERS
    # ============================================================

    def click_with_playwright(self, page, x: float, y: float) -> bool:
        """Координатный клик Playwright для обычных элементов интерфейса."""
        try:
            page.mouse.move(x, y)
            page.mouse.click(x, y)
            return True
        except Exception as e:
            self.log(f"Playwright click failed: {e}")
            return False


    def click_with_cdp(self, page, x: float, y: float) -> bool:
        """Координатный клик через CDP для обычных элементов интерфейса."""
        session = None
        try:
            session = page.context.new_cdp_session(page)
            session.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": x,
                "y": y,
            })
            session.send("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
            session.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
            return True
        except Exception as e:
            self.log(f"CDP click failed: {e}")
            return False
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass


    def click_element_center(self, page, element, prefer_cdp: bool = False) -> bool:
        """Кликает по центру найденного Playwright-элемента."""
        try:
            box = element.bounding_box()
            if not box:
                return False

            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2

            if prefer_cdp:
                if self.click_with_cdp(page, x, y):
                    return True
                return self.click_with_playwright(page, x, y)

            try:
                element.click(timeout=3000)
                return True
            except Exception:
                pass

            if self.click_with_playwright(page, x, y):
                return True

            return self.click_with_cdp(page, x, y)

        except Exception as e:
            self.log(f"click_element_center failed: {e}")
            return False


    def element_is_visible(self, page, selector: str, timeout: int = 800) -> bool:
        """Проверяет видимость обычного элемента интерфейса."""
        try:
            element = page.locator(selector).first
            return (
                element.count() > 0
                and element.is_visible(timeout=timeout)
            )
        except Exception:
            return False


    def wait_until_element_visible(self, page, selector: str, timeout: int = 10000) -> bool:
        """Ждёт появления обычного элемента интерфейса."""
        try:
            page.locator(selector).first.wait_for(
                state="visible",
                timeout=timeout,
            )
            return True
        except Exception:
            return False


    def wait_until_element_hidden(self, page, selector: str, timeout: int = 10000) -> bool:
        """Ждёт исчезновения обычного элемента интерфейса."""
        try:
            page.locator(selector).first.wait_for(
                state="hidden",
                timeout=timeout,
            )
            return True
        except Exception:
            return False


    # ============================================================
    # CLOUDFLARE / ЗАГРУЗКА ИГРЫ
    # ============================================================

    def detect_turnstile(self, page):
        """
        Определяет наличие Cloudflare Turnstile.

        Возвращает:
            "embedded"  - встроенный Turnstile
            "challenge" - challenge-страница Cloudflare
            None        - проверка не обнаружена

        Метод ничего не нажимает.
        """
        session = None

        try:
            session = page.context.new_cdp_session(page)

            root = session.send(
                "DOM.getDocument",
                {"depth": 2},
            )

            node_id = root["root"]["nodeId"]

            embedded = session.send(
                "DOM.querySelector",
                {
                    "nodeId": node_id,
                    "selector": ".cf-turnstile[data-sitekey]",
                },
            )

            if embedded.get("nodeId"):
                return "embedded"

            footer = session.send(
                "DOM.querySelector",
                {
                    "nodeId": node_id,
                    "selector": ".footer-inner",
                },
            )

            footer_id = footer.get("nodeId")

            if footer_id:
                html = session.send(
                    "DOM.getOuterHTML",
                    {"nodeId": footer_id},
                ).get("outerHTML", "")

                keywords = [
                    "Ray ID",
                    "Performance &",
                    "security by",
                    "Cloudflare",
                ]

                if all(keyword in html for keyword in keywords):
                    return "challenge"

        except Exception:
            pass

        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass

        try:
            body_text = page.locator("body").inner_text(
                timeout=1200
            ).lower()

            phrases = [
                "checking that you’re a real player",
                "checking that you're a real player",
                "checking your browser",
                "verify you are human",
                "verifying",
                "идет проверка",
                "идёт проверка",
            ]

            if any(phrase in body_text for phrase in phrases):
                return "challenge"

        except Exception:
            pass

        return None


    def is_cloudflare_active(self, page) -> bool:
        return self.detect_turnstile(page) is not None


    def is_game_interface_ready(self, page) -> bool:
        """Проверяет появление интерфейса Taming.io."""
        selectors = [
            "#serverList",
            "#play-images",
            "div:has-text('Official Server')",
            "text=Official Server",
        ]

        return any(
            self.element_is_visible(
                page,
                selector,
                timeout=500,
            )
            for selector in selectors
        )


    def wait_for_game_ready(self, page) -> bool:
        """
        Ждёт главного интерфейса Taming.io.

        Если Cloudflare появляется, выполнение ставится на паузу
        до ручного прохождения проверки.
        """
        self.log(
            "Ждём Cloudflare и загрузку интерфейса игры..."
        )

        start_time = time.time()
        timeout_seconds = self.game_ready_timeout / 1000

        last_message_time = -10
        previous_cf_type = None

        while time.time() - start_time < timeout_seconds:

            if self.is_game_interface_ready(page):
                self.log("Интерфейс Taming.io загружен.")
                page.wait_for_timeout(2000)
                return True

            cf_type = self.detect_turnstile(page)
            elapsed = int(time.time() - start_time)

            if cf_type is not None and cf_type != previous_cf_type:
                self.log(
                    "Обнаружен Cloudflare Turnstile "
                    f"({cf_type}). "
                    "Ждём ручного подтверждения..."
                )
                previous_cf_type = cf_type
                last_message_time = elapsed

            elif elapsed - last_message_time >= 10:
                last_message_time = elapsed

                if cf_type is not None:
                    self.log(
                        "Cloudflare всё ещё активен. "
                        "Ждём ручного подтверждения..."
                    )
                elif previous_cf_type is not None:
                    self.log(
                        "Cloudflare исчез. "
                        "Ждём главное меню Taming.io..."
                    )
                    previous_cf_type = None
                else:
                    self.log(
                        "Cloudflare не обнаружен, "
                        "ждём интерфейс игры..."
                    )

            page.wait_for_timeout(1000)

        self.log(
            "Интерфейс игры не появился "
            f"за {int(timeout_seconds)} секунд."
        )

        return False


    # ============================================================
    # UPDATE OVERLAY
    # ============================================================

    def close_update_overlay(self, page):
        try:
            btn = page.locator(
                "#update-continue-button"
            ).first

            if btn.is_visible(timeout=12000):
                btn.click(timeout=5000)

                self.log(
                    "Нажат #update-continue-button"
                )

                page.wait_for_timeout(900)

                return

        except Exception:
            pass


        try:
            cross = page.locator(
                'img[src*="white-cross.png"]'
            ).first

            if cross.is_visible(timeout=2500):
                cross.click(timeout=3000)

                self.log(
                    "Оверлей закрыт через white-cross"
                )

                page.wait_for_timeout(900)

                return

        except Exception:
            pass


        self.log(
            "Оверлей не найден (или уже закрыт)."
        )


    # ============================================================
    # CURRENT SERVER
    # ============================================================

    def get_current_server_text(self, page) -> str:
        candidates = [
            "div:has-text('Official Server')",
            "#server-name",
            "[class*='server']",
        ]

        for sel in candidates:
            try:
                el = page.locator(sel).first

                if (
                    el.count() > 0
                    and el.is_visible(timeout=600)
                ):
                    txt = (
                        el.inner_text(timeout=800) or ""
                    ).strip()

                    if txt:
                        return txt

            except Exception:
                pass

        return ""


    def is_current_server(
        self,
        page,
        server_name: str,
    ) -> bool:

        txt = (
            self.get_current_server_text(page)
            .lower()
            .replace(" ", "")
        )

        target = (
            server_name
            .lower()
            .replace(" ", "")
        )

        return target in txt


    # ============================================================
    # OPEN SERVER MENU
    # ============================================================

    def open_server_menu(self, page) -> bool:

        # Возможно меню уже открыто
        try:
            select_button = page.get_by_text(
                "SELECT",
                exact=False,
            ).first

            if select_button.is_visible(timeout=1000):
                self.log(
                    "Меню серверов уже открыто."
                )

                return True

        except Exception:
            pass


        open_candidates = [
            "#serverList",
            "div:has-text('Official Server')",
            "text=Official Server",
            "[class*='server']",
        ]


        for sel in open_candidates:
            try:
                x = page.locator(sel).first

                if (
                    x.count() > 0
                    and x.is_visible(timeout=1500)
                ):
                    if not self.click_element_center(page, x):
                        continue

                    page.wait_for_timeout(1000)


                    # SELECT появился?
                    try:
                        if page.get_by_text(
                            "SELECT",
                            exact=False,
                        ).first.is_visible(
                            timeout=1500
                        ):
                            self.log(
                                "Меню серверов открыто "
                                f"через: {sel}"
                            )

                            return True

                    except Exception:
                        pass


                    # Или появились серверы вида #1, #2...
                    try:
                        if page.locator(
                            "text=/#[0-9]+/"
                        ).first.is_visible(
                            timeout=1500
                        ):
                            self.log(
                                "Меню серверов похоже "
                                f"открыто через: {sel}"
                            )

                            return True

                    except Exception:
                        pass

            except Exception:
                pass


        return False


    # ============================================================
    # CLICK SERVER
    # ============================================================

    def click_server_row(
        self,
        page,
        server_name: str,
    ) -> bool:

        escaped = re.escape(server_name)

        regex = re.compile(
            rf"{escaped}\b",
            re.IGNORECASE,
        )


        # Сначала пробуем нормальный поиск по тексту
        try:
            row = page.get_by_text(
                regex
            ).first

            if (
                row.count() > 0
                and row.is_visible(timeout=2000)
            ):
                row.scroll_into_view_if_needed()

                if not self.click_element_center(page, row):
                    return False

                self.log(
                    "Клик по строке сервера "
                    f"(regex): {server_name}"
                )

                return True

        except Exception:
            pass


        # Fallback
        cards = page.locator(
            "div, tr"
        )

        cnt = min(
            cards.count(),
            700,
        )

        norm_target = (
            server_name
            .lower()
            .replace(" ", "")
        )


        for i in range(cnt):
            c = cards.nth(i)

            try:
                txt = (
                    c.inner_text(timeout=120)
                    or ""
                ).strip()

            except Exception:
                continue


            if not txt:
                continue


            normalized = (
                txt
                .lower()
                .replace(" ", "")
            )


            if (
                norm_target in normalized
                and (
                    "officialserver" in normalized
                    or "select" in normalized
                    or "nextbiome" in normalized
                )
            ):
                try:
                    c.scroll_into_view_if_needed()

                except Exception:
                    pass


                try:
                    c.click(
                        timeout=2500,
                        force=True,
                    )

                    self.log(
                        "Клик по карточке сервера: "
                        f"{server_name}"
                    )

                    return True

                except Exception:
                    pass


        return False


    # ============================================================
    # SELECT BUTTON
    # ============================================================

    def click_select_after_row(self, page) -> bool:

        selectors = [
            ".green-button",
            "button:has-text('SELECT')",
            "text=SELECT",
        ]


        for sel in selectors:
            try:
                button = page.locator(sel).first

                if (
                    button.count() > 0
                    and button.is_visible(timeout=1200)
                ):
                    if not self.click_element_center(page, button):
                        continue

                    self.log(
                        "Нажата кнопка подтверждения: "
                        f"{sel}"
                    )

                    page.wait_for_timeout(700)

                    return True

            except Exception:
                pass


        return False


    # ============================================================
    # SCROLL
    # ============================================================

    def scroll_server_list(
        self,
        page,
        direction="down",
        step=260,
    ):

        candidates = [
            ".simplebar-content-wrapper",
            ".simplebar-content",
            "[class*='scroll']",
            "[class*='list']",
            "[class*='server']",
        ]


        for sel in candidates:
            try:
                box = page.locator(sel).first

                if box.count() == 0:
                    continue


                handle = box.element_handle()

                if handle is None:
                    continue


                can_scroll = page.evaluate(
                    """
                    el =>
                        (el.scrollHeight - el.clientHeight)
                        > 20
                    """,
                    handle,
                )


                if not can_scroll:
                    continue


                dy = (
                    step
                    if direction == "down"
                    else -step
                )


                prev = page.evaluate(
                    "el => el.scrollTop",
                    handle,
                )


                page.evaluate(
                    """
                    (el, d) => {
                        el.scrollTop =
                            el.scrollTop + d;
                    }
                    """,
                    handle,
                    dy,
                )


                page.wait_for_timeout(250)


                new = page.evaluate(
                    "el => el.scrollTop",
                    handle,
                )


                self.log(
                    f"scroll {sel}: {prev} -> {new}"
                )


                return new != prev


            except Exception:
                pass


        return False


    # ============================================================
    # CHOOSE SERVER
    # ============================================================

    def choose_server(
        self,
        page,
        server_name: str,
    ) -> bool:

        if self.is_current_server(
            page,
            server_name,
        ):
            self.log(
                f"{server_name} уже выбран."
            )

            return True


        if not self.open_server_menu(page):
            self.log(
                "Не удалось открыть меню серверов."
            )

            return False


        for pass_idx in range(3):

            self.log(
                f"{server_name}: проход списка "
                f"{pass_idx + 1}/3"
            )


            # Сначала прокручиваем вверх
            for _ in range(4):

                moved = self.scroll_server_list(
                    page,
                    direction="up",
                    step=400,
                )

                if not moved:
                    break


            # Потом ищем вниз
            for _ in range(22):

                clicked_row = self.click_server_row(
                    page,
                    server_name,
                )


                if clicked_row:

                    page.wait_for_timeout(500)


                    if self.is_current_server(
                        page,
                        server_name,
                    ):
                        self.log(
                            f"{server_name}: "
                            "переключился сразу "
                            "после клика строки"
                        )

                        return True


                    for k in range(2):

                        self.click_select_after_row(
                            page
                        )

                        page.wait_for_timeout(700)


                        if self.is_current_server(
                            page,
                            server_name,
                        ):
                            self.log(
                                f"{server_name}: "
                                "переключился после "
                                f"SELECT "
                                f"(попытка {k + 1})"
                            )

                            return True


                moved = self.scroll_server_list(
                    page,
                    direction="down",
                    step=280,
                )


                if not moved:
                    break


        if self.is_current_server(
            page,
            server_name,
        ):
            self.log(
                f"{server_name} подтвержден "
                "в конце fallback."
            )

            return True


        return False


    # ============================================================
    # PLAY
    # ============================================================

    def click_play_and_enter_world(self, page):
        self.log("Ищем кнопку PLAY...")

        page.once(
            "dialog",
            lambda dialog: dialog.dismiss(),
        )

        # Даём интерфейсу чуть-чуть стабилизироваться
        page.wait_for_timeout(1500)

        selectors = [
            "#play-images",
            "#play-button",
            ".play-button",
            "[id*='play']",
            "[class*='play']",
            "button:has-text('Play')",
            "div:has-text('Play')",
            "text=Play",
        ]

        for sel in selectors:
            try:
                locator = page.locator(sel)

                count = locator.count()

                self.log(
                    f"PLAY selector {sel}: найдено {count}"
                )

                for i in range(min(count, 10)):
                    element = locator.nth(i)

                    try:
                        if not element.is_visible(timeout=500):
                            continue

                        box = element.bounding_box()

                        self.log(
                            f"Видимый PLAY элемент: "
                            f"{sel}, index={i}, box={box}"
                        )

                        element.scroll_into_view_if_needed()

                        page.wait_for_timeout(300)

                        # Сначала обычный click
                        try:
                            element.click(
                                timeout=3000
                            )

                            self.log(
                                f"Кликнули PLAY через {sel}"
                            )

                            page.wait_for_timeout(2000)
                            return True

                        except Exception as e:
                            self.log(
                                f"Обычный click не сработал: {e}"
                            )

                        # Потом force click
                        try:
                            element.click(
                                timeout=3000,
                                force=True
                            )

                            self.log(
                                f"Force-клик PLAY через {sel}"
                            )

                            page.wait_for_timeout(2000)
                            return True

                        except Exception as e:
                            self.log(
                                f"Force click не сработал: {e}"
                            )

                        # В крайнем случае JS click
                        try:
                            element.evaluate(
                                "(el) => el.click()"
                            )

                            self.log(
                                f"JS click PLAY через {sel}"
                            )

                            page.wait_for_timeout(2000)
                            return True

                        except Exception as e:
                            self.log(
                                f"JS click не сработал: {e}"
                            )

                    except Exception:
                        continue

            except Exception as e:
                self.log(
                    f"Ошибка selector {sel}: {e}"
                )

        self.log(
            "Кнопка PLAY не была нажата."
        )

        # Сохраняем скрин, чтобы видеть состояние
        try:
            page.screenshot(
                path="debug_play_not_clicked.png",
                full_page=True
            )
        except Exception:
            pass

        return False


    # ============================================================
    # WAIT WORLD
    # ============================================================

    def wait_world_loaded(
        self,
        page,
        server_name,
    ):

        self.log(
            f"{server_name}: ждём загрузку мира..."
        )


        page.wait_for_timeout(5000)


        selectors = [
            "#loading-indicator",
            ".loading",
            "[class*='loading']",
        ]


        for sel in selectors:
            try:
                page.locator(sel).first.wait_for(
                    state="hidden",
                    timeout=20000,
                )

                self.log(
                    f"Loading скрыт: {sel}"
                )

                break

            except Exception:
                pass


        page.wait_for_timeout(4000)


    # ============================================================
    # CHECK ONE SERVER
    # ============================================================

    def create_fresh_page(self, page):
        """
        После успешного скриншота создаём новую вкладку Taming.io
        для следующего сервера и закрываем старую игровую вкладку.

        Старую вкладку закрываем с run_before_unload=False, поэтому
        предупреждение "изменения могут не сохраниться" не должно
        блокировать работу.
        """
        self.log("Готовим чистую вкладку Taming.io для следующего сервера...")

        context = page.context
        new_page = context.new_page()

        try:
            new_page.goto(
                self.base_url,
                wait_until="domcontentloaded",
                timeout=self.nav_timeout,
            )
        except PlaywrightTimeoutError:
            # Страница могла уже начать нормально загружаться.
            self.log(
                "goto() превысил timeout. "
                "Продолжаем ждать интерфейс Taming.io..."
            )

        # Если снова появился Cloudflare, код просто ждёт.
        # При необходимости проверку можно пройти вручную в Opera.
        if not self.wait_for_game_ready(new_page):
            try:
                new_page.screenshot(
                    path="debug_fresh_page_not_ready.png",
                    full_page=True,
                )
            except Exception:
                pass

            try:
                new_page.close(run_before_unload=False)
            except Exception:
                pass

            raise RuntimeError(
                "Новая вкладка Taming.io не загрузила главное меню"
            )

        self.close_update_overlay(new_page)

        # Старую вкладку закрываем только ПОСЛЕ того,
        # как новая вкладка точно готова.
        try:
            page.close(run_before_unload=False)
            self.log("Старая игровая вкладка закрыта.")
        except Exception as e:
            self.log(
                f"Не удалось закрыть старую вкладку: {e}"
            )

        self.log("Новая вкладка Taming.io готова.")
        return new_page


    def check_one(self, page, server_name):
        """
        Проверяет ровно один сервер:
        выбрать сервер -> PLAY -> дождаться мира -> сделать скриншот.

        Здесь НЕТ reload и НЕТ перехода к следующему серверу.
        """
        self.log(
            f"\n=== Проверка {server_name} ==="
        )

        self.log(
            f"Работаем с уже открытой страницей: {page.url}"
        )

        if "taming.io" not in page.url:
            raise RuntimeError(
                f"Открыта не та страница: {page.url}"
            )

        page.wait_for_timeout(1000)

        self.close_update_overlay(page)

        if not self.choose_server(page, server_name):
            current = self.get_current_server_text(page)

            self.log(
                f"Текущий сервер по UI: {current}"
            )

            screenshot_name = (
                "debug_server_select_fail_"
                + server_name.replace("#", "_")
                + ".png"
            )

            page.screenshot(
                path=screenshot_name,
                full_page=True,
            )

            raise RuntimeError(
                f"Не удалось выбрать сервер {server_name}"
            )

        # Нажимаем PLAY только ОДИН раз.
        if not self.click_play_and_enter_world(page):
            raise RuntimeError(
                "Не удалось нажать кнопку PLAY"
            )

        self.wait_world_loaded(
            page,
            server_name,
        )

        out = os.path.join(
            self.screenshot_dir,
            server_name.replace("#", "_") + ".png",
        )

        self.log(
            f"Делаем скриншот {server_name}..."
        )

        page.screenshot(
            path=out,
            full_page=True,
        )

        self.log(
            f"Скриншот сохранён: {out}"
        )


    # ============================================================
    # MAIN CHECK
    # ============================================================

    def check_servers(self):
        os.makedirs(
            self.screenshot_dir,
            exist_ok=True,
        )

        with sync_playwright() as p:
            self.log("Подключаемся к Opera GX...")

            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:9222"
            )

            self.log("Подключились к Opera GX.")

            page = None

            # Ищем уже открытую вручную вкладку Taming.io.
            for context in browser.contexts:
                for current_page in context.pages:
                    if "taming.io" in current_page.url:
                        page = current_page
                        break

                if page is not None:
                    break

            if page is None:
                raise RuntimeError(
                    "Не найдена открытая вкладка Taming.io. "
                    "Открой https://taming.io/ вручную в Opera GX "
                    "и пройди Cloudflare."
                )

            self.log(
                f"Найдена вкладка Taming.io: {page.url}"
            )

            page.wait_for_timeout(2000)

            for i in range(1, self.server_count + 1):
                server_name = f"{self.region}#{i}"
                ok = False

                for attempt in range(
                    1,
                    self.max_server_attempts + 1,
                ):
                    self.log(
                        f"{server_name}: попытка "
                        f"{attempt}/{self.max_server_attempts}"
                    )

                    try:
                        self.check_one(
                            page,
                            server_name,
                        )

                        # Если check_one дошёл сюда, сервер УЖЕ
                        # успешно проверен и скриншот сохранён.
                        ok = True
                        break

                    except PlaywrightTimeoutError as e:
                        self.log(
                            f"Playwright Timeout: {e}"
                        )

                    except Exception as e:
                        self.log(
                            f"Ошибка проверки {server_name}: {e}"
                        )

                    # Повторяем check_one только если сама проверка
                    # сервера не завершилась успешно.
                    if attempt < self.max_server_attempts:
                        self.log(
                            "Повторная попытка через 3 секунды..."
                        )
                        page.wait_for_timeout(3000)

                if not ok:
                    self.log(
                        f"{server_name}: неуспешно после "
                        f"{self.max_server_attempts} попыток"
                    )
                    # Не пытаемся переходить к следующему серверу
                    # из неизвестного состояния игровой вкладки.
                    break

                # После последнего сервера новая вкладка уже не нужна.
                # После КАЖДОГО сервера готовим чистую вкладку.
                # В том числе после последнего, чтобы следующий запуск
                # бота начинался с главного меню Taming.io.
                try:
                    page = self.create_fresh_page(page)

                except Exception as e:
                    self.log(
                        "Сервер успешно проверен, "
                        "но не удалось вернуть Taming.io "
                        f"в главное меню: {e}"
                    )



                time.sleep(2)


# ================================================================
# DIRECT RUN
# ================================================================

if __name__ == "__main__":

    checker = ServerChecker(
        region_name="Frankfurt",
        server_count=3,
        screenshot_dir="screens",
        headless=False,
    )

    checker.check_servers()