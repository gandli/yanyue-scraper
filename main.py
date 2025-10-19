from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)
from urllib.parse import urljoin
import json
import csv

# 传统烟:https://www.yanyue.cn/tobacco
# 低温烟:https://www.yanyue.cn/hnb
# 电子烟:https://www.yanyue.cn/e

BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}


def scrape_tobacco_brands(page):
    container = "#brands"
    try:
        page.wait_for_selector(container, timeout=10000)
    except PlaywrightTimeoutError:
        pass

    results = []
    seen = set()

    def collect_visible_brands(current_tab_label: str):
        anchors = page.locator("#brands a[href]")
        count = anchors.count()
        for i in range(count):
            a = anchors.nth(i)
            try:
                if not a.is_visible():
                    continue
                href = a.get_attribute("href") or ""
                name = (a.inner_text() or "").strip()
                if not href or href.startswith("javascript"):
                    continue
                # 排除非品牌链接，例如“高级搜索”
                if "高级搜索" in name:
                    continue
                # 只保留 /sort/ 开头的品牌链接
                if not href.startswith("/sort/"):
                    continue
                full = urljoin("https://www.yanyue.cn/", href)
                key = (name, full)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"name": name, "href": full, "tab": current_tab_label})
            except PlaywrightError:
                continue

    # 优先使用 #brandsTabs 的 li.brands-tab 进行切换
    tabs_li = page.locator("#brandsTabs li.brands-tab")
    try:
        tab_count = tabs_li.count()
    except PlaywrightError:
        tab_count = 0

    if tab_count and tab_count > 0:
        # 先收集当前（默认）Tab
        try:
            current_label = (page.locator("#brandsTabs li.brands-tab.current").first.inner_text() or "default").strip()
        except PlaywrightError:
            current_label = "default"
        collect_visible_brands(current_label)

        # 逐一点击其他 Tab 并收集
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
        # 回退到通用的 a[role='tab'] 等方案
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


def save_brands(brands, json_path: str, csv_path: str):
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(brands, jf, ensure_ascii=False, indent=2)
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow(["name", "href", "tab"])
        for b in brands:
            writer.writerow([b.get("name", ""), b.get("href", ""), b.get("tab", "")])


def main():
    name, url = ("tobacco", "https://www.yanyue.cn/tobacco")

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

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
            print(f"导航异常: {nav_err}. 继续抓取当前页面状态。")

        # 抓取品牌
        brands = scrape_tobacco_brands(page)
        print(f"抓取到品牌数: {len(brands)}")
        for b in brands[:10]:
            print(f"示例: {b['name']} -> {b['href']} (tab={b['tab']})")

        # 保存文件
        save_brands(brands, "brands_tobacco.json", "brands_tobacco.csv")
        page.screenshot(path=f"yanyue_{name}.png", full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
