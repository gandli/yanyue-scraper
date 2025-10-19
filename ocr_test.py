import os
import glob
from io import BytesIO
from PIL import Image, ImageOps, ImageFilter
import ddddocr

# 目标图片目录（可按需切换品牌目录）
image_dir = 'yanyue_tobacco_output/sort_14/genpic'
image_extensions = ['*.jpg', '*.jpeg', '*.png']

# 初始化 ddddocr（通用 OCR，支持中英文与符号）
reader = ddddocr.DdddOcr(ocr=True, show_ad=False)

# 数字纠错映射（常见误读）：Z->2, S->8, I/l->1, O/o->0, B->8, G->6
DIGIT_MAP = str.maketrans({
    'Z': '2', 'S': '8', 'I': '1', 'l': '1', 'O': '0', 'o': '0', 'B': '8', 'G': '6'
})

def normalize_ocr_digits(s: str) -> str:
    try:
        return s.translate(DIGIT_MAP)
    except Exception:
        return s

# 图像预处理（与 main.py 一致）：灰度、自动对比度、小图放大、轻度锐化
def preprocess_for_ocr(img_path: str):
    try:
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

# 收集图片路径
image_paths = []
for ext in image_extensions:
    image_paths.extend(glob.glob(os.path.join(image_dir, ext)))
    image_paths.extend(glob.glob(os.path.join(image_dir, ext.upper())))

if not image_paths:
    print(f"在目录 {image_dir} 下未找到任何图片文件（支持 jpg, jpeg, png）。")
else:
    print(f"共找到 {len(image_paths)} 张图片，开始 OCR 识别...\n")
    for img_path in sorted(image_paths):
        print(f"正在处理图片：{img_path}")
        try:
            # 预处理 + bytes
            img = preprocess_for_ocr(img_path)
            if img is not None:
                buf = BytesIO()
                img.save(buf, format='PNG')
                img_bytes = buf.getvalue()
            else:
                with open(img_path, 'rb') as f:
                    img_bytes = f.read()

            # 使用 ddddocr 的 classification 识别单行文本
            try:
                raw = reader.classification(img_bytes)
            except Exception:
                raw = ''

            raw_fixed = normalize_ocr_digits(raw.replace('￥', '¥'))
            print(f"识别结果（原始）：'{raw}'")
            print(f"识别结果（纠错）：'{raw_fixed}'")

            # 数值提取演示：仅保留数字与小数点（价格保留¥）
            fname = os.path.basename(img_path)
            if fname.startswith(('pack_price', 'carton_price')):
                val = ''.join([ch for ch in raw_fixed if (ch.isdigit() or ch in ['.', '¥'])])
            elif fname.startswith(('pack_barcode', '条装条码')):
                val = ''.join([ch for ch in raw_fixed if ch.isdigit()])
            else:
                val = ''.join([ch for ch in raw_fixed if (ch.isdigit() or ch == '.')])
                if val.startswith('.') and val[1:].isdigit():
                    val = '0' + val
                if val.endswith('.') and val[:-1].isdigit():
                    val = val[:-1]
            print(f"数值提取：'{val}'\n")
        except Exception as e:
            print(f"处理图片 {img_path} 时出错：{e}\n")

    print("所有图片处理完成。")