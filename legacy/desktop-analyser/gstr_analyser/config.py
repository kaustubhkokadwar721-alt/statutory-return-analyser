"""
Configuration loader for the GSTR Return Analyser.

Reads config.toml from the project root (next to main.py).  All values fall
back to hard-coded defaults so the tool works with a missing or partial file.

Usage anywhere in the package:
    from .config import cfg

    max_workers = cfg.processing.max_workers
    if cfg.checks.is_enabled("RCM_CrossCheck"):
        ...
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any


# ── locate config.toml ────────────────────────────────────────────────────────
# Works whether the tool is run as a script, a package, or a frozen .exe.

def _find_config_path() -> str:
    """Return the absolute path to config.toml, whether frozen or not."""
    if getattr(sys, "frozen", False):
        # PyInstaller: executable lives next to config.toml
        base = os.path.dirname(sys.executable)
    else:
        # Dev / script: config.toml is two levels up from this file
        # gstr_analyser_src/gstr_analyser/config.py  →  gstr_analyser_src/
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "config.toml")


# ── sub-section dataclasses ───────────────────────────────────────────────────

@dataclass
class IdentityConfig:
    firm_name: str   = ""
    engagement: str  = ""
    prepared_by: str = ""


@dataclass
class PathsConfig:
    default_input_dir: str  = ""
    default_output_dir: str = ""


@dataclass
class ProcessingConfig:
    max_workers: int        = 4
    cache_enabled: bool     = True
    cache_max_age_days: int = 30


@dataclass
class OutputConfig:
    gstr1_auditor_filename: str    = "GSTR1_Auditor_Master.xlsx"
    gstr1_analytics_filename: str  = "GSTR1_Analytics_Master.xlsx"
    gstr3b_auditor_filename: str   = "GSTR3B_Auditor_Master.xlsx"
    gstr3b_analytics_filename: str = "GSTR3B_Analytics_Master.xlsx"
    open_on_completion: bool       = False


@dataclass
class FormattingConfig:
    number_format: str    = "indian"    # "indian" | "international"
    date_format: str      = "mmm-yy"   # "mmm-yy" | "mmm-yyyy"
    min_column_width: int = 12

    @property
    def excel_number_format(self) -> str:
        return "##,##,##0" if self.number_format == "indian" else "#,##0"

    @property
    def excel_date_format(self) -> str:
        return self.date_format


_DEFAULT_CHECKS_ENABLED = [
    "Total_Liability",
    "HSN_vs_Supply_Tables",
    "B2CL_Threshold",
    "Record_Count",
    "Interstate_Tax",
    "CDNR_Sign_Check",
    "Payment_Recon_6_1",
    "ITC_Math",
    "RCM_CrossCheck",
]


@dataclass
class ChecksConfig:
    variance_tolerance: float       = 1.0
    hsn_supply_variance_pct: float  = 10.0
    b2cl_invoice_threshold: float   = 250_000.0
    rcm_crosscheck_gap_pct: float   = 10.0
    checks_enabled: list[str]       = field(default_factory=lambda: list(_DEFAULT_CHECKS_ENABLED))

    def is_enabled(self, check_name: str) -> bool:
        """Return True if check_name (or a prefix of it) is in the enabled list.

        Prefix matching lets "ITC_Math" cover "ITC_Math_Integrated_tax" etc.
        """
        for enabled in self.checks_enabled:
            if check_name == enabled or check_name.startswith(enabled):
                return True
        return False


@dataclass
class TemplatesConfig:
    gstr1_template: str  = ""
    gstr3b_template: str = ""

    def get(self, return_type: str) -> str | None:
        """Return the template path for 'gstr1' or 'gstr3b', or None if unset."""
        path = self.gstr1_template if return_type == "gstr1" else self.gstr3b_template
        return path.strip() or None


# ── top-level config object ───────────────────────────────────────────────────

@dataclass
class AppConfig:
    identity: IdentityConfig      = field(default_factory=IdentityConfig)
    paths: PathsConfig            = field(default_factory=PathsConfig)
    processing: ProcessingConfig  = field(default_factory=ProcessingConfig)
    output: OutputConfig          = field(default_factory=OutputConfig)
    formatting: FormattingConfig  = field(default_factory=FormattingConfig)
    checks: ChecksConfig          = field(default_factory=ChecksConfig)
    templates: TemplatesConfig    = field(default_factory=TemplatesConfig)

    def summary_header(self, return_type: str) -> tuple[str, str]:
        """Return (title_line, subtitle_line) for the Summary sheet header.

        return_type: 'gstr1' | 'gstr3b'
        """
        label = "GSTR-1" if return_type == "gstr1" else "GSTR-3B"
        if self.identity.firm_name:
            title = f"{self.identity.firm_name}  —  {label} Analytics"
        else:
            title = f"{label} Analytics Summary"

        parts = []
        if self.identity.engagement:
            parts.append(self.identity.engagement)
        if self.identity.prepared_by:
            parts.append(f"Prepared by: {self.identity.prepared_by}")
        subtitle = "  ·  ".join(parts) if parts else ""

        return title, subtitle


# ── loader ────────────────────────────────────────────────────────────────────

def _get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safe nested dict lookup with a default."""
    node = data
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
        if node is default:
            return default
    return node


def _load_toml(path: str) -> dict:
    try:
        import tomllib                    # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib       # pip install tomli (3.9/3.10 fallback)
        except ImportError:
            return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"[config] Warning: could not parse config.toml: {exc}", file=sys.stderr)
        return {}


def load_config(path: str | None = None) -> AppConfig:
    """Load AppConfig from *path* (defaults to auto-detected config.toml)."""
    config_path = path or _find_config_path()
    data = _load_toml(config_path)

    def _section(key: str) -> dict:
        return data.get(key, {}) if isinstance(data, dict) else {}

    id_ = _section("identity")
    pa  = _section("paths")
    pr  = _section("processing")
    ou  = _section("output")
    fo  = _section("formatting")
    ch  = _section("checks")
    tm  = _section("templates")

    return AppConfig(
        identity=IdentityConfig(
            firm_name   = str(id_.get("firm_name",   "")),
            engagement  = str(id_.get("engagement",  "")),
            prepared_by = str(id_.get("prepared_by", "")),
        ),
        paths=PathsConfig(
            default_input_dir  = str(pa.get("default_input_dir",  "")),
            default_output_dir = str(pa.get("default_output_dir", "")),
        ),
        processing=ProcessingConfig(
            max_workers        = int(pr.get("max_workers",        4)),
            cache_enabled      = bool(pr.get("cache_enabled",     True)),
            cache_max_age_days = int(pr.get("cache_max_age_days", 30)),
        ),
        output=OutputConfig(
            gstr1_auditor_filename    = str(ou.get("gstr1_auditor_filename",    "GSTR1_Auditor_Master.xlsx")),
            gstr1_analytics_filename  = str(ou.get("gstr1_analytics_filename",  "GSTR1_Analytics_Master.xlsx")),
            gstr3b_auditor_filename   = str(ou.get("gstr3b_auditor_filename",   "GSTR3B_Auditor_Master.xlsx")),
            gstr3b_analytics_filename = str(ou.get("gstr3b_analytics_filename", "GSTR3B_Analytics_Master.xlsx")),
            open_on_completion        = bool(ou.get("open_on_completion",       False)),
        ),
        formatting=FormattingConfig(
            number_format    = str(fo.get("number_format",    "indian")),
            date_format      = str(fo.get("date_format",      "mmm-yy")),
            min_column_width = int(fo.get("min_column_width", 12)),
        ),
        checks=ChecksConfig(
            variance_tolerance      = float(ch.get("variance_tolerance",      1.0)),
            hsn_supply_variance_pct = float(ch.get("hsn_supply_variance_pct", 10.0)),
            b2cl_invoice_threshold  = float(ch.get("b2cl_invoice_threshold",  250_000.0)),
            rcm_crosscheck_gap_pct  = float(ch.get("rcm_crosscheck_gap_pct",  10.0)),
            checks_enabled          = list(ch.get("checks_enabled", _DEFAULT_CHECKS_ENABLED)),
        ),
        templates=TemplatesConfig(
            gstr1_template  = str(tm.get("gstr1_template",  "")),
            gstr3b_template = str(tm.get("gstr3b_template", "")),
        ),
    )


# ── module-level singleton ────────────────────────────────────────────────────
# Import this in any module:  from .config import cfg
cfg: AppConfig = load_config()
