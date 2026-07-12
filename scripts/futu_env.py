from __future__ import annotations

import os
import socket
import sys
from pathlib import Path


DEFAULT_FUTU_HOST = "127.0.0.1"
DEFAULT_FUTU_PORT = 11111
DEFAULT_FUTU_TIMEOUT = 2.0


def load_repo_env(root: Path) -> None:
    env_path = Path(root) / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def get_futu_host() -> str:
    return str(os.environ.get("FUTU_HOST", DEFAULT_FUTU_HOST)).strip() or DEFAULT_FUTU_HOST


def get_futu_port() -> int:
    raw = str(os.environ.get("FUTU_PORT", "")).strip()
    try:
        return int(raw or DEFAULT_FUTU_PORT)
    except ValueError:
        return DEFAULT_FUTU_PORT


def get_futu_timeout() -> float:
    raw = str(os.environ.get("FUTU_CONNECT_TIMEOUT", "")).strip()
    try:
        return float(raw or DEFAULT_FUTU_TIMEOUT)
    except ValueError:
        return DEFAULT_FUTU_TIMEOUT


def probe_futu_socket(host: str, port: int, timeout_s: float) -> tuple[bool, str]:
    probe = socket.socket()
    probe.settimeout(timeout_s)
    try:
        probe.connect((host, port))
        return True, "tcp connect ok"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        probe.close()


def ensure_futu_socket_or_die(root: Path, *, stream=None) -> tuple[str, int]:
    stream = stream or sys.stderr
    load_repo_env(root)
    host = get_futu_host()
    port = get_futu_port()
    timeout_s = get_futu_timeout()
    ok, detail = probe_futu_socket(host, port, timeout_s)
    if ok:
        return host, port
    print(f"ERROR: FutuOpenD not reachable at {host}:{port}: {detail}", file=stream)
    print(f"TIP: run {root / 'scripts' / 'check_futu_setup.py'} for a full Futu/OpenD probe", file=stream)
    raise SystemExit(2)


def ensure_futu_quote_backend_or_die(root: Path, *, sample_symbol: str = "HK.00700", stream=None) -> tuple[str, int]:
    stream = stream or sys.stderr
    host, port = ensure_futu_socket_or_die(root, stream=stream)
    try:
        from futu import OpenQuoteContext, RET_OK
    except Exception as exc:
        print(f"ERROR: futu SDK import failed after socket probe: {exc}", file=stream)
        raise SystemExit(2)

    ctx = None
    try:
        ctx = OpenQuoteContext(host=host, port=port)
        ret, data = ctx.get_global_state()
        qot_logined = None
        trd_logined = None
        if ret == RET_OK:
            if isinstance(data, dict):
                qot_logined = bool(data.get("qot_logined"))
                trd_logined = bool(data.get("trd_logined"))
            elif hasattr(data, "to_dict"):
                rows = data.to_dict(orient="records")
                if rows:
                    row = rows[0]
                    qot_logined = bool(row.get("qot_logined"))
                    trd_logined = bool(row.get("trd_logined"))
        if qot_logined is False:
            print(
                f"ERROR: FutuOpenD socket is up at {host}:{port}, but quote backend is not logged in "
                f"(qot_logined={qot_logined}, trd_logined={trd_logined})",
                file=stream,
            )
            local_rs = get_local_futu_opend_rs_info()
            if local_rs:
                print(
                    f"TIP: local futu-opend-rs detected at {local_rs['exe']}. "
                    f"Run {root / 'scripts' / 'start_futu_opend_rs.py'} in foreground for SMS/device verification, "
                    f"or use --verify-code <SMS_CODE>.",
                    file=stream,
                )
            print(f"TIP: run {root / 'scripts' / 'check_futu_setup.py'} for backend status details", file=stream)
            raise SystemExit(3)

        if sample_symbol:
            ret2, snap = ctx.get_market_snapshot([sample_symbol])
            if ret2 != RET_OK:
                print(
                    f"ERROR: FutuOpenD connected at {host}:{port}, but sample quote {sample_symbol} is unavailable: {snap}",
                    file=stream,
                )
                print(f"TIP: run {root / 'scripts' / 'check_futu_setup.py'} for backend status details", file=stream)
                raise SystemExit(3)
        return host, port
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: Futu quote backend probe failed at {host}:{port}: {exc}", file=stream)
        print(f"TIP: run {root / 'scripts' / 'check_futu_setup.py'} for backend status details", file=stream)
        raise SystemExit(3)
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


def find_local_futu_opend_rs_dirs() -> list[Path]:
    home = Path.home()
    base = home / "futu-opend"
    if not base.exists():
        return []
    candidates = []
    for child in base.glob("futu-opend-rs-*"):
        exe = child / "futu-opend.exe"
        if exe.exists():
            candidates.append(child)
    return sorted(candidates, reverse=True)


def get_local_futu_opend_rs_info() -> dict | None:
    dirs = find_local_futu_opend_rs_dirs()
    if not dirs:
        return None
    root = dirs[0]
    return {
        "root": root,
        "exe": root / "futu-opend.exe",
        "config": root / "futu-opend.toml",
        "stdout_log": root / "opend_stdout.log",
        "stderr_log": root / "opend_stderr.log",
    }
