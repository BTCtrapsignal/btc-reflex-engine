"""
BTC Reflex Engine — Safety Tests

Verifies critical isolation guarantees.
These tests must always pass before deployment.
"""
import ast
import os
import pytest
from pathlib import Path


REFLEX_ROOT = Path(__file__).parent.parent / "app"
BRAIN_OPS_MODULES = [
    "btc_brain", "brain_ops", "btc_ops", "signal_alert",
    "btc_signal", "brain_memory", "brain_core",
]


def _all_python_files(root: Path) -> list[Path]:
    return list(root.rglob("*.py"))


def _get_imports(filepath: Path) -> list[str]:
    """Extract all import module names from a Python file."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


# ── Test 1: No Brain Ops imports anywhere in Reflex ──────────────────────────

def test_no_brain_ops_imports():
    """
    Reflex must never import from BTC Brain Ops modules.
    The only allowed Brain integration is brain_reader.py via HTTP.
    """
    files = _all_python_files(REFLEX_ROOT)
    violations = []
    for f in files:
        if "brain_reader" in str(f):
            continue  # brain_reader itself is the controlled integration point
        for imp in _get_imports(f):
            for brain_mod in BRAIN_OPS_MODULES:
                if brain_mod in imp.lower():
                    violations.append(f"{f}: imports '{imp}'")
    assert not violations, f"Brain Ops imports found:\n" + "\n".join(violations)


# ── Test 2: brain_reader.py never writes ─────────────────────────────────────

def test_brain_reader_is_readonly():
    """
    brain_reader.py must never contain write operations.
    Only GET requests are allowed.
    """
    brain_reader = REFLEX_ROOT / "integrations" / "brain_reader.py"
    assert brain_reader.exists(), "brain_reader.py not found"

    content = brain_reader.read_text()
    forbidden = ["requests.post", "requests.put", "requests.patch", "requests.delete"]
    violations = [f for f in forbidden if f in content]
    assert not violations, (
        f"brain_reader.py contains write HTTP operations: {violations}"
    )


# ── Test 3: No shared ENV namespace ──────────────────────────────────────────

def test_env_namespace_separation():
    """
    All Reflex env vars must use REFLEX_ prefix.
    No Brain Ops env var names may appear in Reflex config.
    """
    config_path = REFLEX_ROOT / "config.py"
    assert config_path.exists(), "config.py not found"

    content = config_path.read_text()
    brain_env_keys = [
        "BOT_TOKEN", "CHAT_ID", "DATABASE_URL", "BRAIN_BOT",
        "SIGNAL_", "OPS_DATABASE",
    ]
    violations = []
    for key in brain_env_keys:
        # Allow REFLEX_ prefixed versions
        if key in content and f"REFLEX_{key}" not in content:
            violations.append(key)
    assert not violations, (
        f"Config uses non-prefixed env var names: {violations}"
    )


# ── Test 4: Mode must default to observer ────────────────────────────────────

def test_default_mode_is_observer():
    """System must default to observer mode — never execution."""
    config_path = REFLEX_ROOT / "config.py"
    content = config_path.read_text()
    assert '"observer"' in content or "'observer'" in content, (
        "Default mode must be 'observer' in config.py"
    )


# ── Test 5: No SQLAlchemy write operations in brain_reader ───────────────────

def test_no_db_writes_in_brain_reader():
    """brain_reader.py must never contain DB session or ORM operations."""
    brain_reader = REFLEX_ROOT / "integrations" / "brain_reader.py"
    content = brain_reader.read_text()
    forbidden = ["db.add(", "db.commit(", "session.add(", "session.commit(", "SessionLocal"]
    violations = [f for f in forbidden if f in content]
    assert not violations, (
        f"brain_reader.py contains DB write operations: {violations}"
    )


# ── Test 6: Context assembler never sends trade commands ─────────────────────

def test_no_trade_commands_in_narrative():
    """
    Behavioral context assembler must never output trade command strings.
    Observer mode means description only.
    """
    assembler_path = REFLEX_ROOT / "engines" / "context_assembler.py"
    content = assembler_path.read_text().lower()
    forbidden_phrases = [
        "buy now", "sell now", "go long", "go short",
        "enter long", "enter short", "open position", "place order",
        "execute trade", "market buy", "market sell",
    ]
    violations = [p for p in forbidden_phrases if p in content]
    assert not violations, (
        f"context_assembler.py contains trade commands: {violations}"
    )


# ── Test 7: All engines accept empty input gracefully ────────────────────────

def test_engines_handle_empty_candles():
    """All engines must return a valid state when given empty candle lists."""
    import sys
    sys.path.insert(0, str(REFLEX_ROOT.parent))

    from app.engines.structure_engine import StructureEngine
    from app.engines.rotation_engine import RotationEngine, RotationObservation
    from app.engines.choch_engine import CHoCHEngine
    from app.engines.volatility_engine import VolatilityEngine

    se = StructureEngine()
    result = se.analyze([], "4H")
    assert result.structure_type == "unknown"

    re = RotationEngine()
    state = se.analyze([], "4H")
    result = re.analyze([], state)
    assert result.boundary == "none"

    ce = CHoCHEngine()
    result = ce.analyze([])
    assert result.choch_detected is False

    ve = VolatilityEngine()
    result = ve.analyze([])
    assert result.state == "unknown"


# ── Test 8: Memory layer never writes to Brain Ops ────────────────────────────

def test_memory_layer_isolated():
    """Memory layer must only write to Reflex DB — never Brain Ops."""
    mem_path = REFLEX_ROOT / "database" / "memory_layer.py"
    assert mem_path.exists(), "memory_layer.py not found"
    content = mem_path.read_text()

    # Must not import anything from Brain Ops
    for brain_mod in BRAIN_OPS_MODULES:
        assert brain_mod not in content.lower(), (
            f"memory_layer.py references Brain Ops module: {brain_mod}"
        )

    # Must not make HTTP requests (no requests.post/put to external systems)
    assert "requests.post" not in content, "memory_layer.py must not make HTTP POST calls"
    assert "requests.put"  not in content, "memory_layer.py must not make HTTP PUT calls"


# ── Test 9: Memory tables have no Brain Ops foreign keys ─────────────────────

def test_memory_tables_isolated():
    """Memory tables must reference only Reflex tables — never Brain Ops tables."""
    models_path = REFLEX_ROOT / "database" / "models.py"
    content = models_path.read_text()

    brain_table_names = [
        "brain_signals", "brain_memory", "brain_ops_", "btc_brain",
        "signal_alerts", "ops_observations",
    ]
    for tname in brain_table_names:
        assert tname not in content.lower(), (
            f"models.py references Brain Ops table: {tname}"
        )
