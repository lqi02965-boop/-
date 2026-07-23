import os
import sys
import subprocess

def run_cmd(cmd):
    """运行终端命令并实时打印输出"""
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(line, end="")
    process.wait()
    return process.returncode

def setup():
    print("==================================================")
    print("🚀 开始自动创建虚拟环境与安装项目所有依赖...")
    print("==================================================\n")

    venv_dir = "venv_attendance"
    
    # 1. 创建虚拟环境
    if not os.path.exists(venv_dir):
        print(f"📦 1. 正在创建虚拟环境 [{venv_dir}]...")
        code = run_cmd(f'"{sys.executable}" -m venv {venv_dir}')
        if code != 0:
            print("❌ 虚拟环境创建失败，请检查 Python 环境！")
            return
        print("✅ 虚拟环境创建成功！\n")
    else:
        print(f"ℹ️ 虚拟环境 [{venv_dir}] 已存在，跳过创建步骤。\n")

    # 确定虚拟环境中的 python/pip 路径
    if sys.platform == "win32":
        pip_path = os.path.join(venv_dir, "Scripts", "pip.exe")
        python_path = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        pip_path = os.path.join(venv_dir, "bin", "pip")
        python_path = os.path.join(venv_dir, "bin", "python")

    # 2. 升级 pip
    print("🔄 2. 正在升级 pip...")
    run_cmd(f'"{pip_path}" install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple')
    print("")

    # 3. 安装依赖清单 (使用清华镜像源)
    packages = [
        "PySide6",
        "opencv-python",
        "mediapipe==0.10.14",
        "insightface",
        "onnxruntime",
        "numpy",
        "pandas",
        "openpyxl"
    ]

    print("⚡ 3. 正在批量安装依赖库，请稍等...")
    install_cmd = f'"{pip_path}" install {" ".join(packages)} -i https://pypi.tuna.tsinghua.edu.cn/simple'
    code = run_cmd(install_cmd)

    if code == 0:
        print("\n==================================================")
        print("🎉 环境配置全部成功完成！")
        print("==================================================")
        print(f"👉 你可以使用以下命令直接启动考勤系统：")
        print(f"   {python_path} .\\4.py\n")
    else:
        print("\n❌ 部分依赖安装失败，请检查网络连接后重试！")

if __name__ == "__main__":
    setup()