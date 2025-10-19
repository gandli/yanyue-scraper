from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)
from urllib.parse import urljoin
import json
import csv
import os

# 传统烟:https://www.yanyue.cn/tobacco
# 低温烟:https://www.yanyue.cn/hnb
# 电子烟:https://www.yanyue.cn/e

BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}


def ensure_dir(dir_path: str):
    os.makedirs(dir_path, exist_ok=True)


# 公共：收集可见链接并按规则过滤，写入 results（去重）
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
            full = urljoin("https://www.yanyue.cn/", href)
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
            current_label = (page.locator("#brandsTabs li.brands-tab.current").first.inner_text() or "default").strip()
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


def main():
    targets = [
        {
            "name": "tobacco",
            "url": "https://www.yanyue.cn/tobacco",
            "output_dir": "yanyue_tobacco_output",
            "scraper": scrape_tobacco_brands,
            "headers": ("name", "href", "tab"),
        },
        {
            "name": "hnb",
            "url": "https://www.yanyue.cn/hnb",
            "output_dir": "yanyue_hnb_output",
            "scraper": scrape_hnb,
            "headers": ("name", "href", "section"),
        },
        {
            "name": "e",
            "url": "https://www.yanyue.cn/e",
            "output_dir": "yanyue_e_output",
            "scraper": scrape_e,
            "headers": ("name", "href", "section"),
        },
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            ),
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
            try:
                page.goto(t["url"], wait_until="domcontentloaded", timeout=60000)
                # 某些页面有“内容加载中”倒计时，等待其消失或回退
                try:
                    page.wait_for_selector("text=内容加载中", timeout=2000)
                    page.wait_for_selector("text=内容加载中", state="hidden", timeout=10000)
                except PlaywrightTimeoutError:
                    page.wait_for_timeout(5000)
            except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                print(f"导航异常: {nav_err}. 继续抓取当前页面状态。")

            brands = t["scraper"](page)
            print(f"[{t['name']}] 抓取到品牌/目录数: {len(brands)}")
            out_json = os.path.join(t["output_dir"], f"brands_{t['name']}.json")
            out_csv = os.path.join(t["output_dir"], f"brands_{t['name']}.csv")
            save_brands(brands, out_json, out_csv, headers=t["headers"])
            page.screenshot(path=os.path.join(t["output_dir"], f"yanyue_{t['name']}.png"), full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
