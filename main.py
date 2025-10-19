from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)

# 传统烟:https://www.yanyue.cn/tobacco
# 低温烟:https://www.yanyue.cn/hnb
# 电子烟:https://www.yanyue.cn/e

BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}


def main():
    targets = [
        ("tobacco", "https://www.yanyue.cn/tobacco"),
        ("hnb", "https://www.yanyue.cn/hnb"),
        ("e", "https://www.yanyue.cn/e"),
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

        for name, url in targets:
            # 样式统一允许加载，其他非文本资源继续阻断
            allow_styles = True

            # 重置并设置当前页面的路由规则
            try:
                page.unroute("**/*")
            except PlaywrightError:
                pass

            def route_handler(route, request):
                rt = request.resource_type
                if rt in BLOCKED_TYPES and not (allow_styles and rt == "stylesheet"):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", route_handler)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if allow_styles:
                    # 站点会显示“内容加载中…还剩5秒”，等待其消失或超时回退
                    try:
                        page.wait_for_selector("text=内容加载中", timeout=2000)
                        page.wait_for_selector("text=内容加载中", state="hidden", timeout=10000)
                    except PlaywrightTimeoutError:
                        page.wait_for_timeout(7000)
            except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                print(f"导航异常: {nav_err}. 继续截图当前页面状态。")

            title = page.title()
            print(f"{name} 标题: {title}")
            page.screenshot(path=f"yanyue_{name}.png", full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
