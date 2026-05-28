"""中短线主板爆发力个股扫描器 (Pro Scanner)

按"团队炒股方案"§2.1–§2.2 的三共振（题材/资金/技术）筛选与打分逻辑实现。
仅作为筛选工具：输出符合特征的候选池，**不构成投资建议**，明天涨跌仍由市场决定。
"""

from stock_picker.scanner_pro.runner import run_scanner_pro

__all__ = ["run_scanner_pro"]
