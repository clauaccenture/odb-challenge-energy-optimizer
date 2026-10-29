from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


root = Path(SPECPATH)
scripts = (
    "01_ingesta_redata.py", "01_ingesta_aemet.py",
    "02_calidad_redata.py", "02_calidad_aemet.py",
    "03_gold_redata.py", "03_gold_aemet.py",
)
datas = [(str(root / "notebooks" / name), "notebooks") for name in scripts]
datas += [
    (str(root / "app" / "streamlit_app.py"), "app"),
    (str(root / "app" / "data_loader.py"), "app"),
    (str(root / ".env.example"), "."),
]
datas += collect_data_files("streamlit")
datas += collect_data_files("plotly")
datas += copy_metadata("streamlit")

analysis = Analysis(
    [str(root / "run_local.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=[
        "pandas", "numpy", "pyarrow", "pyarrow.parquet",
        "requests", "boto3", "plotly.graph_objects", "streamlit.web.cli",
        "streamlit.runtime.scriptrunner.magic_funcs",
    ],
    excludes=["matplotlib", "IPython", "pytest", "torch", "tensorflow"],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [],
    exclude_binaries=True,
    name="EnergyOptimizer",
    console=True,
    upx=False,
)
collect = COLLECT(
    exe, analysis.binaries, analysis.datas,
    name="EnergyOptimizer",
    upx=False,
)
