from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)
from urllib.parse import urljoin
import json
import csv
import os
import re

# --- OCR engine (ddddocr) initialization and preprocessing helpers ---
DDDDOCR_READER = None

def get_ddddocr_reader():
    global DDDDOCR_READER
    if DDDDOCR_READER is None:
        try:
            import ddddocr
            # Enable general OCR (supports Chinese and English), CPU only
            DDDDOCR_READER = ddddocr.DdddOcr(ocr=True, show_ad=False)
        except Exception:
            DDDDOCR_READER = None
    return DDDDOCR_READER


def preprocess_for_ocr(img_path: str):
    try:
        from PIL import Image, ImageOps, ImageFilter
        img = Image.open(img_path)
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img)
        w, h = img.size
        if max(w, h) < 120:
            img = img.resize((w * 2, h * 2), Image.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
        return img
    except Exception:
        return None

# 传统烟:https://www.yanyue.cn/tobacco
# 低温烟:https://www.yanyue.cn/hnb
# 电子烟:https://www.yanyue.cn/e

BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}
CRAWL_DELAY_MS = 10000  # 10s
YANYUE_USER_AGENT = "SeekportBot"
# YANYUE_LIMIT_BRANDS = 2
# YANYUE_LIMIT_PRODUCT_PAGES = 2
# YANYUE_LIMIT_DETAILS = 5


def ensure_dir(dir_path: str):
    os.makedirs(dir_path, exist_ok=True)


# 公共：收集可见链接并按规则过滤，写入 results（去重）
# 站点地址常量（替换原注释为变量）
BASE_URL = "https://www.yanyue.cn"
TOBACCO_URL = f"{BASE_URL}/tobacco"
HNB_URL = f"{BASE_URL}/hnb"
E_URL = f"{BASE_URL}/e"
ASHIMA_URL = f"{BASE_URL}/sort/14"


def collect_anchors(
    page,
    anchor_selector: str,
    results: list,
    seen: set,
    href_prefix: str | None = None,
    exclude_names: list[str] | None = None,
    extra_fields: dict | None = None,
):
    anchors = page.locator(anchor_selector)
    try:
        count = anchors.count()
    except PlaywrightError:
        count = 0
    for i in range(count):
        a = anchors.nth(i)
        try:
            if not a.is_visible():
                continue
            href = a.get_attribute("href") or ""
            name = (a.inner_text() or "").strip()
            if not href or href.startswith("javascript") or href.startswith("#"):
                continue
            if not name:
                continue
            if exclude_names and any(ex in name for ex in exclude_names):
                continue
            full = urljoin(BASE_URL + "/", href)
            if href_prefix:
                prefix_full = urljoin(BASE_URL + "/", href_prefix.lstrip("/"))
                if not full.startswith(prefix_full):
                    continue
            key = (name, full)
            if key in seen:
                continue
            seen.add(key)
            item = {"name": name, "href": full}
            if extra_fields:
                item.update(extra_fields)
            results.append(item)
        except PlaywrightError:
            continue


def scrape_tobacco_brands(page):
    container = "#brands"
    try:
        page.wait_for_selector(container, timeout=10000)
    except PlaywrightTimeoutError:
        pass

    results = []
    seen = set()

    def collect_visible_brands(current_tab_label: str):
        collect_anchors(
            page,
            "#brands a[href]",
            results,
            seen,
            href_prefix="/sort/",
            exclude_names=["高级搜索"],
            extra_fields={"tab": current_tab_label},
        )

    tabs_li = page.locator("#brandsTabs li.brands-tab")
    try:
        tab_count = tabs_li.count()
    except PlaywrightError:
        tab_count = 0

    if tab_count and tab_count > 0:
        try:
            current_label = (
                page.locator("#brandsTabs li.brands-tab.current").first.inner_text()
                or "default"
            ).strip()
        except PlaywrightError:
            current_label = "default"
        collect_visible_brands(current_label)

        for i in range(tab_count):
            t = tabs_li.nth(i)
            try:
                label = (t.inner_text() or "").strip() or f"tab_{i}"
            except PlaywrightError:
                label = f"tab_{i}"
            try:
                t.click(timeout=5000)
                page.wait_for_timeout(400)
            except PlaywrightError:
                pass
            collect_visible_brands(label)
    else:
        generic_tabs = page.locator(
            "#brands .nav-tabs a, #brands .tabs a, #brands [role='tab'], #brands .tab-title a, #brands .tabbar a"
        )
        try:
            gcount = generic_tabs.count()
        except PlaywrightError:
            gcount = 0
        if gcount and gcount > 0:
            for i in range(gcount):
                t = generic_tabs.nth(i)
                try:
                    label = (t.inner_text() or "").strip() or f"tab_{i}"
                except PlaywrightError:
                    label = f"tab_{i}"
                try:
                    t.click(timeout=5000)
                    page.wait_for_timeout(400)
                except PlaywrightError:
                    pass
                collect_visible_brands(label)
        else:
            collect_visible_brands("default")

    return results


def scrape_hnb(page):
    container = "body > div.main.clearfix > div.root61.pt20.clearfix"
    try:
        page.wait_for_selector(container, timeout=10000)
    except PlaywrightTimeoutError:
        pass

    results = []
    seen = set()
    collect_anchors(
        page,
        f"{container} a[href]",
        results,
        seen,
        href_prefix="/sorte/",
        exclude_names=["高级搜索"],
        extra_fields={"section": "hnb"},
    )
    return results


def scrape_e(page):
    container = "body > div.main.clearfix > div.root61.pt20.clearfix > div"
    try:
        page.wait_for_selector(container, timeout=10000)
    except PlaywrightTimeoutError:
        pass

    results = []
    seen = set()
    collect_anchors(
        page,
        f"{container} a[href]",
        results,
        seen,
        href_prefix="/sorte/",
        exclude_names=["高级搜索"],
        extra_fields={"section": "e"},
    )
    return results


def save_brands(brands, json_path: str, csv_path: str, headers=("name", "href", "tab")):
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(brands, jf, ensure_ascii=False, indent=2)
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow(list(headers))
        for b in brands:
            writer.writerow([b.get(h, "") for h in headers])


def load_json_if_exists(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            return []
    return []


def append_ndjson(file_path: str, obj: dict):
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass


def append_csv_row(file_path: str, headers: tuple, row_dict: dict):
    need_header = not os.path.exists(file_path) or os.path.getsize(file_path) == 0
    with open(file_path, "a", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        if need_header:
            writer.writerow(list(headers))
        writer.writerow([row_dict.get(h, "") for h in headers])


def load_ndjson_hrefs(path: str) -> set:
    hrefs = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line.strip())
                        href = obj.get("href")
                        if href:
                            hrefs.add(href)
                    except Exception:
                        continue
        except Exception:
            pass
    return hrefs


def ocr_genpic(
    img_locator, save_dir: str | None, filename_prefix: str, idx: int
) -> dict:
    path = ""
    src = ""
    try:
        src = img_locator.get_attribute("src") or ""
    except PlaywrightError:
        src = ""
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        try:
            path = os.path.join(save_dir, f"{filename_prefix}_{idx}.png")
            img_locator.screenshot(path=path)
        except PlaywrightError:
            path = ""
    text = ""
    try:
        reader = get_ddddocr_reader()
        if reader and path:
            from io import BytesIO
            img = preprocess_for_ocr(path)
            if img is not None:
                buf = BytesIO()
                img.save(buf, format="PNG")
                img_bytes = buf.getvalue()
            else:
                with open(path, "rb") as f:
                    img_bytes = f.read()
            # Prefer general OCR (supports Chinese + symbols); fallback to classification
            out = reader.ocr(img_bytes)
            if out:
                raw = "".join([
                    (item.get("text", "") if isinstance(item, dict) else str(item))
                    for item in out
                ]).strip()
            else:
                try:
                    raw = reader.classification(img_bytes)
                except Exception:
                    raw = ""
            raw = raw.replace("￥", "¥")
            # Field-specific normalization: keep expected characters
            numeric_keys = {
                "tar",
                "nicotine",
                "co",
                "length",
                "filter_length",
                "circumference",
                "per_pack_count",
                "packs_per_carton",
                "pack_price",
                "carton_price",
                "pack_barcode",
                "条装条码",
            }
            if filename_prefix in {"pack_price", "carton_price"}:
                text = re.sub(r"[^0-9.¥]", "", raw)
            elif filename_prefix in {"pack_barcode", "条装条码"}:
                text = re.sub(r"[^0-9]", "", raw)
            elif filename_prefix in numeric_keys:
                text = re.sub(r"[^0-9.]", "", raw)
                # normalize decimals like '.5' -> '0.5' and '1.' -> '1'
                if text.startswith(".") and text[1:].isdigit():
                    text = "0" + text
                if text.endswith(".") and text[:-1].isdigit():
                    text = text[:-1]
            else:
                text = raw
    except Exception:
        text = ""
    return {"text": text, "path": path, "src": src}


def navigate_and_wait(
    page,
    url: str,
    content_selector: str | None = None,
    timeout_ms: int = 60000,
    retries: int = 0,
):
    last_err = None
    for attempt in range(retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_selector("text=内容加载中", timeout=2000)
                page.wait_for_selector("text=内容加载中", state="hidden", timeout=10000)
            except PlaywrightTimeoutError:
                page.wait_for_timeout(500)
            if content_selector:
                try:
                    page.wait_for_selector(content_selector, timeout=10000)
                except PlaywrightTimeoutError:
                    pass
            # 每次导航后统一等待 Crawl-delay
            page.wait_for_timeout(CRAWL_DELAY_MS)
            return True
        except (PlaywrightTimeoutError, PlaywrightError) as e:
            last_err = e
            page.wait_for_timeout(1000)
    return False


def scrape_brand_products(page, brand_url: str, max_pages: int = 100):
    results = []
    seen = set()

    def collect_current_page():
        collect_anchors(
            page,
            "#left #prowrap a[href]",
            results,
            seen,
            href_prefix="/product/",
            exclude_names=["更多信息", "评论"],
            extra_fields=None,
        )

    def click_next_page() -> bool:
        selectors = [
            "a[rel='next']",
            "a:has-text('下一页')",
            ".pages a:has-text('下一页')",
            "#left a:has-text('下一页')",
            "#prowrap a:has-text('下一页')",
            "a:has-text('下一页>')",
            "a:has-text('下一页»')",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    next_a = loc.first
                    if next_a.is_visible():
                        next_a.click(timeout=5000)
                        page.wait_for_load_state("domcontentloaded")
                        # 分页导航后等待 5s，遵守 Crawl-delay
                        page.wait_for_timeout(CRAWL_DELAY_MS)
                        return True
            except PlaywrightError:
                continue
        return False

    # 仅在当前不在目标品牌页时才导航，避免重复等待
    if page.url != brand_url:
        navigate_and_wait(page, brand_url, content_selector="#prowrap", retries=1)

    for _ in range(max_pages):
        collect_current_page()
        if not click_next_page():
            break

    return results


def scrape_product_detail(page, img_save_dir: str | None = None) -> dict:
    details = {
        "name": "",
        "href": page.url,
        "heat": "",
        "kouwei": "",
        "waiguan": "",
        "xingjiabi": "",
        "zonghe": "",
    }
    try:
        container = page.locator("#product_detail")
        if container.count() > 0:
            try:
                details_text = container.inner_text()
            except PlaywrightError:
                details_text = ""
        else:
            details_text = ""

        # 名称
        name_selectors = [
            "#product_detail h1",
            "#product_detail .title",
            "#product_detail .pname",
            "#product_detail h2",
        ]
        for sel in name_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = (loc.first.inner_text() or "").strip()
                    if text:
                        details["name"] = text
                        break
            except PlaywrightError:
                continue
        if not details["name"]:
            try:
                details["name"] = (page.title() or "").strip()
            except PlaywrightError:
                details["name"] = ""

        # 热度与评分
        if details_text:
            m = re.search(r"热度[:：]\s*(\d+)", details_text)
            if m:
                details["heat"] = m.group(1)

            def find_score(label_regex):
                m = re.search(
                    label_regex + r"[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*分", details_text
                )
                return m.group(1) if m else ""

            details["kouwei"] = find_score(r"口\s*味")
            details["waiguan"] = find_score(r"外\s*观")
            details["xingjiabi"] = find_score(r"性\s*价\s*比")
            details["zonghe"] = find_score(r"综\s*合")

        # 解析 ul.ul_1 属性对（支持 genpic 图片数字）
        try:
            ul = page.locator("#product_detail ul.ul_1")
            if ul.count() > 0:
                lis = ul.locator("li")
                lc = lis.count()
                title_map = {
                    "品牌": "brand",
                    "类型": "type",
                    "焦油": "tar",
                    "烟碱": "nicotine",
                    "一氧化碳": "co",
                    "长度": "length",
                    "过滤嘴长": "filter_length",
                    "周长": "circumference",
                    "包装形式": "packaging",
                    "主颜色": "main_color",
                    "副颜色": "sub_color",
                    "每盒数量": "per_pack_count",
                    "条装盒数": "packs_per_carton",
                    "小盒价格": "pack_price",
                    "条装价格": "carton_price",
                    "小盒条码": "pack_barcode",
                }
                for i in range(lc):
                    try:
                        li = lis.nth(i)
                        cls = li.get_attribute("class") or ""
                        if "info_title" in cls:
                            title = ((li.inner_text() or "").strip()).rstrip(":：")
                            key = title_map.get(title, title)
                            # 下一个 sibling 作为内容
                            if i + 1 < lc:
                                content_li = lis.nth(i + 1)
                                val_text = (content_li.inner_text() or "").strip()
                                imgs = content_li.locator("img.genpic")
                                ocr_val = ""
                                if imgs.count() > 0:
                                    parts = []
                                    save_dir = (
                                        os.path.join(img_save_dir or "", "genpic")
                                        if img_save_dir
                                        else None
                                    )
                                    for j in range(imgs.count()):
                                        r = ocr_genpic(
                                            imgs.nth(j), save_dir, f"{key}", j + 1
                                        )
                                        if r.get("text"):
                                            parts.append(r["text"])
                                    if parts:
                                        ocr_val = "".join(parts)
                                value = ocr_val or val_text
                                details[key] = value
                    except PlaywrightError:
                        continue
        except PlaywrightError:
            pass

        # 原始文本备份（仅 JSON 输出，不写入 CSV）
        details["detail_text"] = details_text or ""
    except PlaywrightError:
        pass

    return details


def main():
    targets = [
        {
            "name": "tobacco",
            "url": TOBACCO_URL,
            "output_dir": "yanyue_tobacco_output",
            "scraper": scrape_tobacco_brands,
            "headers": ("name", "href", "tab"),
        },
        {
            "name": "hnb",
            "url": HNB_URL,
            "output_dir": "yanyue_hnb_output",
            "scraper": scrape_hnb,
            "headers": ("name", "href", "section"),
        },
        {
            "name": "e",
            "url": E_URL,
            "output_dir": "yanyue_e_output",
            "scraper": scrape_e,
            "headers": ("name", "href", "section"),
        },
    ]

    with sync_playwright() as p:
        # 使用常量 UA 与 Crawl-delay 配置
        chosen_ua = YANYUE_USER_AGENT
        # 使用常量 CRAWL_DELAY_MS=10000（10s）

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=chosen_ua,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        # 统一允许样式，其它非文本资源继续阻断
        try:
            page.unroute("**/*")
        except PlaywrightError:
            pass

        def route_handler(route, request):
            try:
                rt = request.resource_type
                url = request.url or ""
                # 放行 genpic 反爬数字图片，其它图片仍阻断
                if rt == "image":
                    if "genpic" in url:
                        route.continue_()
                    else:
                        route.abort()
                    return
                if rt in BLOCKED_TYPES and not (rt == "stylesheet"):
                    route.abort()
                else:
                    route.continue_()
            except PlaywrightError:
                route.continue_()

        page.route("**/*", route_handler)

        for t in targets:
            ensure_dir(t["output_dir"])
            ok = navigate_and_wait(
                page, t["url"], retries=1
            )  # 每次导航后统一 Crawl-delay
            if not ok:
                print(f"导航异常: 无法进入 {t['url']}。继续抓取当前页面状态。")

            brands = t["scraper"](page)
            print(f"[{t['name']}] 抓取到品牌/目录数: {len(brands)}")
            out_json = os.path.join(t["output_dir"], f"brands_{t['name']}.json")
            out_csv = os.path.join(t["output_dir"], f"brands_{t['name']}.csv")
            save_brands(brands, out_json, out_csv, headers=t["headers"])
            page.screenshot(
                path=os.path.join(t["output_dir"], f"yanyue_{t['name']}.png"),
                full_page=True,
            )

        # --- 抓取所有传统烟品牌的产品与详情 ---
        brands_json_path = os.path.join("yanyue_tobacco_output", "brands_tobacco.json")
        tobacco_brands = load_json_if_exists(brands_json_path)
        if tobacco_brands:
            print(f"[tobacco] 复用已有品牌列表: {len(tobacco_brands)}")
        else:
            ok = navigate_and_wait(page, TOBACCO_URL, retries=1)
            if not ok:
                print("[tobacco] 导航失败，仍尝试从当前页面抓取品牌。")
            tobacco_brands = scrape_tobacco_brands(page)
            print(f"[tobacco] 需要抓取的品牌数: {len(tobacco_brands)}")

        products_max_pages_env = os.getenv("YANYUE_LIMIT_PRODUCT_PAGES", "")
        try:
            products_max_pages = (
                int(products_max_pages_env) if products_max_pages_env.strip() else 100
            )
        except ValueError:
            products_max_pages = 100

        limit_details_env = os.getenv("YANYUE_LIMIT_DETAILS", "")
        try:
            limit_details = (
                int(limit_details_env) if limit_details_env.strip() else None
            )
        except ValueError:
            limit_details = None

        # 限制品牌数量以便快速验证（可选）
        limit_brands_env = os.getenv("YANYUE_LIMIT_BRANDS", "")
        try:
            limit_brands = int(limit_brands_env) if limit_brands_env.strip() else None
        except ValueError:
            limit_brands = None
        if limit_brands is not None:
            tobacco_brands = tobacco_brands[:limit_brands]
            print(f"[tobacco] 将处理前 {limit_brands} 个品牌")

        total_brands = len(tobacco_brands)
        for i, b in enumerate(tobacco_brands, 1):
            href = b.get("href") or ""
            name = b.get("name") or "unknown"
            m = re.search(r"/sort/(\d+)", href)
            if not m:
                continue
            brand_id = m.group(1)
            brand_url = href if href.startswith("http") else urljoin(BASE_URL, href)
            brand_dir = os.path.join("yanyue_tobacco_output", f"sort_{brand_id}")
            ensure_dir(brand_dir)

            print(
                f"[brand {i}/{total_brands} id:{brand_id}] 进入品牌页: {name} -> {brand_url}"
            )
            navigate_and_wait(page, brand_url, content_selector="#prowrap", retries=1)
            page.screenshot(
                path=os.path.join(brand_dir, f"brand_sort_{brand_id}.png"),
                full_page=True,
            )

            products_json_path = os.path.join(
                brand_dir, f"sort_{brand_id}_products.json"
            )
            products_csv_path = os.path.join(brand_dir, f"sort_{brand_id}_products.csv")
            products = load_json_if_exists(products_json_path)
            if products:
                print(f"[brand:{brand_id}] 复用已存在产品列表: {len(products)}")
            else:
                products = scrape_brand_products(
                    page, brand_url, max_pages=products_max_pages
                )
                print(f"[brand:{brand_id}] 产品列表数量: {len(products)}")
            # 确保产品列表持久化（复用时也生成CSV）
            save_brands(
                products,
                products_json_path,
                products_csv_path,
                headers=("name", "href"),
            )

            details = []
            details_stream_ndjson_path = os.path.join(
                brand_dir, f"sort_{brand_id}_details_stream.ndjson"
            )
            details_stream_csv_path = os.path.join(
                brand_dir, f"sort_{brand_id}_details_stream.csv"
            )
            seen_detail_hrefs = load_ndjson_hrefs(details_stream_ndjson_path)
            detail_headers = (
                "name",
                "href",
                "heat",
                "kouwei",
                "waiguan",
                "xingjiabi",
                "zonghe",
                "type",
                "tar",
                "nicotine",
                "co",
                "length",
                "filter_length",
                "circumference",
                "packaging",
                "main_color",
                "sub_color",
                "per_pack_count",
                "packs_per_carton",
                "pack_price",
                "carton_price",
                "pack_barcode",
            )
            for idx, p in enumerate(products):
                if limit_details is not None and idx >= limit_details:
                    break
                url = p.get("href")
                if not url:
                    continue
                if url in seen_detail_hrefs:
                    print(f"[detail:{brand_id}] 已存在，跳过: {url}")
                    continue
                print(f"[detail:{brand_id}] ({idx + 1}/{len(products)}) 进入: {url}")
                ok2 = navigate_and_wait(
                    page, url, content_selector="#product_detail", retries=2
                )
                if not ok2:
                    print(f"[detail:{brand_id}] 跳过无法进入的产品页: {url}")
                    continue
                d = scrape_product_detail(page, img_save_dir=brand_dir)
                details.append(d)
                append_ndjson(details_stream_ndjson_path, d)
                append_csv_row(details_stream_csv_path, detail_headers, d)
                seen_detail_hrefs.add(url)
                if idx < 3:
                    page.screenshot(
                        path=os.path.join(brand_dir, f"product_{idx + 1}.png"),
                        full_page=True,
                    )
            print(f"[detail:{brand_id}] 完成产品详情抓取: {len(details)}")
            save_brands(
                details,
                os.path.join(brand_dir, f"sort_{brand_id}_details.json"),
                os.path.join(brand_dir, f"sort_{brand_id}_details.csv"),
                headers=detail_headers,
            )

        browser.close()


if __name__ == "__main__":
    main()
