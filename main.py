import flet as ft
import requests
import threading
import json
import time


# --- 核心邏輯區 ---
class CustomsQuery:
    def __init__(self):
        self.url = "https://portal.sw.nat.gov.tw/APGQ/GB312_query0"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://portal.sw.nat.gov.tw",
            "Referer": "https://portal.sw.nat.gov.tw/",
        }
        self.session = requests.Session()

    def fetch_data(self, vsl_reg_no, status_callback=None, query_code=None):
        """執行查詢並回傳結果列表 (List[Dict])

        - 使用自動分頁 (tab0.currentPage / tab0.rowNum)
        - status_callback: 用來回報進度，例如 "正在讀取第 X 頁..."
        - query_code: 這次查詢使用的掛號（南掛/北掛），會加到每筆 item 的 `query_code` 欄位
        """
        # 沒指定 query_code 就以傳入的 vsl_reg_no 為主
        if query_code is None:
            query_code = vsl_reg_no

        # 1. 初始化 Session（模擬瀏覽器先開主頁）
        try:
            self.session.get(
                "https://portal.sw.nat.gov.tw/APGQ/GB312",
                headers=self.headers,
                timeout=10,
            )
        except Exception:
            # 初始化失敗不致命，繼續試著查詢
            pass

        all_results = []
        current_page = 1
        page_size = 500  # 一次抓 500 筆，減少請求次數

        while True:
            # 回報進度給 UI
            if status_callback:
                status_callback(f"正在讀取第 {current_page} 頁資料...")

            payload = {
                "tab0.currentPage": str(current_page),
                "tab0.rowNum": str(page_size),
                "tab0.vslRegNo": vsl_reg_no,
                "tab0.choice": "1",  # 1 = 依船機查詢
                "tab0.soNoStart": "0000",  # S/O 起
                "tab0.soNoEnd": "Z",  # S/O 迄（全船）
                "tab0.declCustCd": "BC",
                "tab0.mawbStart": "",
                "tab0.mawbEnd": "",
                "tab0.hawb": "",
                "tab0.storWareCd": "",
                "tab0.declNo": "",
            }

            try:
                resp = self.session.post(
                    self.url,
                    headers=self.headers,
                    data=payload,
                    timeout=20,
                )
            except Exception as e:
                # 第一頁就失敗：直接回傳錯誤
                if not all_results:
                    return [{"error": f"連線失敗：{e}"}]
                # 後面頁數失敗：回傳目前已抓到的資料
                break

            if resp.status_code != 200:
                if not all_results:
                    return [{"error": f"伺服器錯誤：HTTP {resp.status_code}"}]
                break

            try:
                json_data = resp.json()
            except Exception as e:
                if not all_results:
                    return [{"error": f"資料解析錯誤：{e}", "raw": resp.text[:200]}]
                break

            total_count = json_data.get("total", 0)
            raw_data = json_data.get("data", [])

            # 這一頁完全沒資料，直接結束
            if not raw_data:
                break

            # 解析這一頁，加入總清單
            parsed_page = self._parse_json_list(raw_data, query_code=query_code)
            all_results.extend(parsed_page)

            # 若已抓到的筆數 >= 伺服器回報的 total，代表已抓完
            if len(all_results) >= total_count:
                break

            # 還沒抓完，準備下一頁
            current_page += 1
            time.sleep(0.2)  # 小延遲，避免被當成攻擊或被限流

        return all_results

    def _parse_json_list(self, raw_list, query_code=None):
        """解析 JSON data list，轉成乾淨的資料結構

        欄位：
          - soNo        -> S/O Number（主標題）
          - declNo      -> 報單號（仍保留在資料，但 UI 不顯示）
          - vslName     -> 船名
          - packQty1    -> 件數（0 或 None 要處理）
          - inWareDate1 -> 進倉時間，格式：YYYYMMDD HHMMSS -> YYYY/MM/DD HH:mm
          - query_code  -> 查詢使用的掛號（南掛/北掛）
        """
        results = []
        for row in raw_list:
            raw_date = row.get("inWareDate1")
            fmt_date = "尚無時間"
            if raw_date and isinstance(raw_date, str) and len(raw_date) >= 12:
                try:
                    # 例如：20251216 153545 -> 2025/12/16 15:35
                    yyyy = raw_date[0:4]
                    mm = raw_date[4:6]
                    dd = raw_date[6:8]
                    hh = raw_date[9:11]
                    minute = raw_date[11:13]
                    fmt_date = f"{yyyy}/{mm}/{dd} {hh}:{minute}"
                except Exception:
                    fmt_date = raw_date

            qty = row.get("packQty1")
            # 件數處理：None 或 0 都轉成 "0"
            try:
                qty_str = str(int(qty)) if qty is not None else "0"
            except Exception:
                qty_str = "0"

            item = {
                "so_no": row.get("soNo", "無 S/O"),
                "decl_no": row.get("declNo", ""),  # 雖然 UI 不顯示，但先保留
                "vsl_name": row.get("vslName", ""),
                "qty": qty_str,
                "date": fmt_date,
                "query_code": query_code or "",
            }
            results.append(item)
        return results


# --- UI 介面區 ---
def main(page: ft.Page):
    page.title = "貨況查詢小幫手（雙掛號版）"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 420
    page.window_height = 720
    page.vertical_alignment = ft.MainAxisAlignment.START

    # 供南掛/北掛記憶用的 Key
    SOUTH_KEY = "last_south_code"
    NORTH_KEY = "last_north_code"

    query_service = CustomsQuery()

    # --- UI 元件定義 ---
    # 讀取上次的掛號記憶
    last_south = page.client_storage.get(SOUTH_KEY) or ""
    last_north = page.client_storage.get(NORTH_KEY) or ""

    txt_south = ft.TextField(
        label="南掛 (South Call Sign)",
        value=last_south,
        expand=True,
        autofocus=True,
    )

    txt_north = ft.TextField(
        label="北掛 (North Call Sign)",
        value=last_north,
        expand=True,
    )

    # S/O 本地端篩選輸入框
    txt_filter_so = ft.TextField(
        label="搜尋 S/O (Filter S/O)",
        hint_text="輸入 S/O 關鍵字即時篩選",
        dense=True,
        on_change=None,  # 稍後綁定事件
    )

    btn_query = ft.ElevatedButton(
        "查詢",
        icon=ft.Icons.SEARCH,
        on_click=None,  # 稍後再綁定
    )

    result_list = ft.ListView(
        expand=True,
        spacing=10,
        padding=20,
    )

    loading = ft.ProgressBar(
        visible=False,
    )

    status_text = ft.Text(
        "準備就緒",
        color="black",
        size=12,
    )

    # 儲存目前查詢到的「全部結果」，供本地端 S/O 篩選使用
    all_results = []

    # --- 顯示結果列表（不處理篩選，只單純畫畫面） ---
    def show_results(data):
        result_list.controls.clear()

        if not data:
            result_list.controls.append(ft.Text("查無資料", color="red"))
            page.update()
            return

        if isinstance(data[0], dict) and "error" in data[0]:
            # 顯示錯誤訊息
            err = data[0].get("error", "未知錯誤")
            result_list.controls.append(
                ft.Text(f"錯誤：{err}", color="red")
            )
            raw_snippet = data[0].get("raw")
            if raw_snippet:
                result_list.controls.append(
                    ft.Text(
                        f"伺服器回應片段：{raw_snippet}",
                        size=10,
                        selectable=True,
                    )
                )
            page.update()
            return

        # 這裡可以視需求排序，例如依 S/O 排序
        # data.sort(key=lambda x: x["so_no"])

        for item in data:
            card = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            # 第一行：S/O + 件數 badge
                            ft.Row(
                                [
                                    ft.Text(
                                        f"S/O: {item['so_no']}",
                                        weight=ft.FontWeight.BOLD,
                                        size=18,
                                        color="blue",
                                    ),
                                    ft.Container(
                                        content=ft.Text(
                                            f"{item['qty']} 件",
                                            color="white",
                                            size=12,
                                        ),
                                        bgcolor="green",
                                        padding=ft.padding.symmetric(
                                            horizontal=8,
                                            vertical=4,
                                        ),
                                        border_radius=10,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            # 第二行：掛號（由 query_code 顯示，取代原本的報單）
                            ft.Text(
                                f"掛號：{item.get('query_code', '')}",
                                size=14,
                                selectable=True,
                            ),
                            ft.Divider(height=10, color="transparent"),
                            # 第三行：船名 + 進倉時間
                            ft.Row(
                                [
                                    ft.Text(
                                        f"船名：{item['vsl_name']}",
                                        size=12,
                                        color="grey",
                                    ),
                                    ft.Text(
                                        f"進倉：{item['date']}",
                                        size=12,
                                        color="black",
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                        ]
                    ),
                    padding=15,
                )
            )
            result_list.controls.append(card)

        page.update()

    # --- 依照 txt_filter_so 的內容，從 all_results 做本地端 S/O 篩選 ---
    def apply_filter():
        keyword = (txt_filter_so.value or "").strip()

        if not all_results:
            show_results([])
            return

        if not keyword:
            show_results(all_results)
            return

        filtered = [
            item
            for item in all_results
            if keyword.lower() in str(item.get("so_no", "")).lower()
        ]
        show_results(filtered)

    txt_filter_so.on_change = lambda e: apply_filter()

    # --- 雙掛號查詢流程 ---
    def start_query():
        nonlocal all_results

        south_code = (txt_south.value or "").strip()
        north_code = (txt_north.value or "").strip()

        if not south_code and not north_code:
            status_text.value = "請先輸入南掛或北掛掛號"
            page.update()
            return

        # 將目前輸入的掛號記住在 client_storage
        try:
            page.client_storage.set(SOUTH_KEY, south_code)
            page.client_storage.set(NORTH_KEY, north_code)
        except Exception:
            # 儲存失敗不影響查詢流程
            pass

        # UI 進入「查詢中」狀態
        loading.visible = True
        btn_query.disabled = True
        status_text.value = "開始查詢..."
        result_list.controls.clear()
        page.update()

        # 後端更新狀態的 callback（供 CustomsQuery 使用）
        def update_status(msg: str):
            status_text.value = msg
            page.update()

        def task():
            nonlocal all_results
            try:
                combined_results = []
                error_messages = []

                # 先查南掛
                if south_code:
                    status_text.value = f"查詢中（南掛：{south_code}）..."
                    page.update()
                    data_south = query_service.fetch_data(
                        south_code,
                        status_callback=update_status,
                        query_code=south_code,
                    )
                    if (
                        data_south
                        and isinstance(data_south[0], dict)
                        and "error" in data_south[0]
                    ):
                        error_messages.append(f"南掛 {south_code} 查詢失敗：{data_south[0].get('error')}")
                    else:
                        combined_results.extend(data_south)

                # 再查北掛
                if north_code:
                    status_text.value = f"查詢中（北掛：{north_code}）..."
                    page.update()
                    data_north = query_service.fetch_data(
                        north_code,
                        status_callback=update_status,
                        query_code=north_code,
                    )
                    if (
                        data_north
                        and isinstance(data_north[0], dict)
                        and "error" in data_north[0]
                    ):
                        error_messages.append(f"北掛 {north_code} 查詢失敗：{data_north[0].get('error')}")
                    else:
                        combined_results.extend(data_north)

                # 查詢結束，還原 UI 狀態
                loading.visible = False
                btn_query.disabled = False

                # 若全部都失敗，顯示第一個錯誤即可
                if not combined_results and error_messages:
                    status_text.value = "查詢失敗，請稍後再試"
                    show_results(
                        [
                            {
                                "error": "；".join(error_messages),
                            }
                        ]
                    )
                    return

                # 無資料
                if not combined_results:
                    status_text.value = "查詢完成：查無資料"
                    all_results = []
                    show_results([])
                    return

                # 成功有資料
                all_results = combined_results
                total_count = len(all_results)

                if error_messages:
                    # 部分成功，部分失敗
                    status_text.value = f"查詢完成，共 {total_count} 筆資料（但有部分掛號查詢失敗）"
                else:
                    status_text.value = f"查詢完成，共 {total_count} 筆資料"

                # 初次顯示時先套用目前的篩選條件
                apply_filter()

            except Exception as e:
                loading.visible = False
                btn_query.disabled = False
                status_text.value = "查詢過程發生未預期錯誤"
                result_list.controls.clear()
                result_list.controls.append(
                    ft.Text(
                        f"錯誤：{e}",
                        color="red",
                    )
                )
                page.update()

        threading.Thread(target=task, daemon=True).start()

    # Button 的 on_click -> 呼叫 start_query
    def run_query(e):
        start_query()

    btn_query.on_click = run_query

    # 版面配置
    page.add(
        ft.Column(
            [
                # 南掛 / 北掛 輸入列
                ft.Row(
                    [txt_south, txt_north],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # 查詢按鈕
                ft.Row(
                    [btn_query],
                    alignment=ft.MainAxisAlignment.END,
                ),
                # S/O 本地端搜尋
                txt_filter_so,
                loading,
                status_text,
                ft.Divider(),
                result_list,
            ],
            expand=True,
        )
    )


ft.app(target=main)
