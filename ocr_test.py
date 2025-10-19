import easyocr
import glob
import os

# 初始化 OCR 读者，支持简体中文和英文
reader = easyocr.Reader(['ch_sim', 'en'])  # 只需初始化一次

# 图片文件夹路径
image_dir = 'yanyue_tobacco_output/sort_14/genpic'

# 支持的图片格式
image_extensions = ['*.jpg', '*.jpeg', '*.png']  # 可根据需要添加更多如 *.bmp, *.tiff 等

# 获取该目录下所有图片的完整路径
image_paths = []
for ext in image_extensions:
    image_paths.extend(glob.glob(os.path.join(image_dir, ext)))
    image_paths.extend(glob.glob(os.path.join(image_dir, ext.upper())))  # 如 *.JPG, *.PNG

# 检查是否找到图片
if not image_paths:
    print(f"在目录 {image_dir} 下未找到任何图片文件（支持 jpg, jpeg, png）。")
else:
    print(f"共找到 {len(image_paths)} 张图片，开始 OCR 识别...")
    
    # 遍历每张图片并进行 OCR
    for img_path in image_paths:
        print(f"\n正在处理图片：{img_path}")
        try:
            result = reader.readtext(img_path)
            print(f"识别结果（原始格式）：")
            for detection in result:
                # detection 格式: (bbox, text, confidence)
                bbox, text, conf = detection
                print(f"  文本：'{text}'，置信度：{conf:.2f}")
        except Exception as e:
            print(f"处理图片 {img_path} 时出错：{e}")

    print("\n所有图片处理完成。")