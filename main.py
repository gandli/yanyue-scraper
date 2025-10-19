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

# 传统烟:https://www.yanyue.cn/tobacco
# 低温烟:https://www.yanyue.cn/hnb
# 电子烟:https://www.yanyue.cn/e

BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}
CRAWL_DELAY_MS = 10000  # 10s
YANYUE_USER_AGENT = "SeekportBot"  


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
            if href_prefix and not href.startswith(href_prefix):
                continue
            full = urljoin(BASE_URL + "/", href)
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


def navigate_and_wait(
    page, url: str, content_selector: str | None = None, timeout_ms: int = 60000
):
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
        # 统一在每次导航后等待 5s，遵守 robots.txt 的 Crawl-delay
        page.wait_for_timeout(CRAWL_DELAY_MS)
        return True
    except (PlaywrightTimeoutError, PlaywrightError):
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

    navigate_and_wait(page, brand_url, content_selector="#prowrap")

    for _ in range(max_pages):
        collect_current_page()
        if not click_next_page():
            break

    return results


def scrape_product_detail(page) -> dict:
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

        # 热度
        if details_text:
            m = re.search(r"热度[:：]\s*(\d+)", details_text)
            if m:
                details["heat"] = m.group(1)

            # 分数提取（兼容空格/全角空格）
            def find_score(label_regex):
                m = re.search(
                    label_regex + r"[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*分", details_text
                )
                return m.group(1) if m else ""

            details["kouwei"] = find_score(r"口\s*味")
            details["waiguan"] = find_score(r"外\s*观")
            details["xingjiabi"] = find_score(r"性\s*价\s*比")
            details["zonghe"] = find_score(r"综\s*合")

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
        # 读取 UA 与 Crawl-delay 配置
        ua_env = os.getenv("YANYUE_USER_AGENT", "").strip()
        default_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        )
        chosen_ua = ua_env if ua_env else default_ua

        # 根据 UA 或环境变量动态设置 Crawl-delay
        global CRAWL_DELAY_MS
        crawl_delay_env = os.getenv("YANYUE_CRAWL_DELAY_MS", "").strip()
        try:
            CRAWL_DELAY_MS = (
                int(crawl_delay_env)
                if crawl_delay_env
                else (10000 if "seekportbot" in chosen_ua.lower() else 5000)
            )
        except ValueError:
            CRAWL_DELAY_MS = 10000 if "seekportbot" in chosen_ua.lower() else 5000

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
            rt = request.resource_type
            if rt in BLOCKED_TYPES and not (rt == "stylesheet"):
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)

        for t in targets:
            ensure_dir(t["output_dir"])
            ok = navigate_and_wait(page, t["url"])  # 每次导航后统一 Crawl-delay
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
        ok = navigate_and_wait(page, TOBACCO_URL)
        if not ok:
            print("[tobacco] 导航失败，仍尝试从当前页面抓取品牌。")
        tobacco_brands = scrape_tobacco_brands(page)
        print(f"[tobacco] 需要抓取的品牌数: {len(tobacco_brands)}")

        products_max_pages_env = os.getenv("YANYUE_LIMIT_PRODUCT_PAGES", "")
        try:
            products_max_pages = int(products_max_pages_env) if products_max_pages_env.strip() else 100
        except ValueError:
            products_max_pages = 100

        limit_details_env = os.getenv("YANYUE_LIMIT_DETAILS", "")
        try:
            limit_details = int(limit_details_env) if limit_details_env.strip() else None
        except ValueError:
            limit_details = None

        for b in tobacco_brands:
            href = b.get("href") or ""
            name = b.get("name") or "unknown"
            if not href.startswith("/sort/"):
                continue
            m = re.search(r"/sort/(\d+)", href)
            brand_id = m.group(1) if m else "unknown"
            brand_url = urljoin(BASE_URL, href)
            brand_dir = os.path.join("yanyue_tobacco_output", f"sort_{brand_id}")
            ensure_dir(brand_dir)

            print(f"[brand:{brand_id}] 进入品牌页: {name} -> {brand_url}")
            navigate_and_wait(page, brand_url, content_selector="#prowrap")
            page.screenshot(path=os.path.join(brand_dir, f"brand_sort_{brand_id}.png"), full_page=True)

            products = scrape_brand_products(page, brand_url, max_pages=products_max_pages)
            print(f"[brand:{brand_id}] 产品列表数量: {len(products)}")
            save_brands(
                products,
                os.path.join(brand_dir, f"sort_{brand_id}_products.json"),
                os.path.join(brand_dir, f"sort_{brand_id}_products.csv"),
                headers=("name", "href"),
            )

            details = []
            for idx, p in enumerate(products):
                if limit_details is not None and idx >= limit_details:
                    break
                url = p.get("href")
                if not url:
                    continue
                ok2 = navigate_and_wait(page, url, content_selector="#product_detail")
                if not ok2:
                    print(f"[detail:{brand_id}] 跳过无法进入的产品页: {url}")
                    continue
                d = scrape_product_detail(page)
                details.append(d)
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
                headers=("name", "href", "heat", "kouwei", "waiguan", "xingjiabi", "zonghe"),
            )

    browser.close()


if __name__ == "__main__":
    main()
