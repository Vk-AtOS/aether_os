"""Python AST security checks for generated FastAPI backends.

SEC-001 hard-coded credential literal         SEC-002 signing secret with a literal default
SEC-004 SQL built from f-string/concat/format  SEC-005 eval/exec/pickle/yaml.load/shell=True/os.system
SEC-006 debug / reload left on                 SEC-009 CORS wildcard origin with credentials
SEC-010 JWT decoded without a fixed algorithm list or with verification off
SEC-011 weak or missing password hashing       SEC-018 TLS verification disabled
SEC-019 `random` used for tokens / OTPs
"""
from __future__ import annotations

import ast
import re

from aether_os.core.rulepacks.base import Finding, Project, call_name, const_str, dotted, is_true, kw, make

PACK = "security"
SECRET_NAME = re.compile(r"(?:password|passwd|secret|secret_key|api_?key|access_?key|private_?key|client_?secret|"
                         r"auth_?token|access_?token|refresh_?token|bearer_?token|webhook_?secret)$", re.I)
SIGNING_NAME = re.compile(r"(?:^|_)(?:secret_key|jwt_secret(?:_key)?|jwt_key|signing_key|session_secret|app_secret|token_secret)$", re.I)
PLACEHOLDER = re.compile(r"change|example|your|xxx|placeholder|dummy|sample|<|\$\{|\{\{|replace|todo|fake|redacted|"
                         r"\*\*\*|not[-_ ]?set|^\s*$", re.I)
SQL_WORD = re.compile(r"\b(select|insert|update|delete|where|from|into|values|drop|alter|create)\b", re.I)
HASH_LIBS = re.compile(r"\b(passlib|bcrypt|argon2|pwdlib|scrypt|werkzeug\.security|pbkdf2_hmac|CryptContext)\b")
WEAK_SCHEMES = {"md5_crypt", "des_crypt", "plaintext", "ldap_md5", "ldap_plaintext", "hex_md5", "hex_sha1",
                "sha1_crypt", "bsdi_crypt", "unix_disabled"}
TOKEN_FUNC = re.compile(r"token|otp|secret|password|nonce|salt|reset|verif|api_?key", re.I)


def _looks_secret(value: str) -> bool:
    return (len(value) >= 8 and not re.search(r"\s", value) and not PLACEHOLDER.search(value) and not value.isupper()
            and not value.startswith(("/", "http://localhost", "env:")))


def _target_name(t: ast.AST) -> str:
    return t.id if isinstance(t, ast.Name) else (t.attr if isinstance(t, ast.Attribute) else "")


def _default_value(node: ast.AST | None) -> str | None:
    """Literal default from `"x"`, `Field("x")`, `Field(default="x")`."""
    s = const_str(node)
    if s is not None:
        return s
    if isinstance(node, ast.Call) and call_name(node).split(".")[-1] == "Field":
        return const_str(node.args[0]) if node.args else const_str(kw(node, "default"))
    return None


def _main_guard_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test):
            ids |= {id(x) for x in ast.walk(n)}
    return ids


def _secrets(p: Project, rel: str, tree: ast.AST, out: list[Finding]) -> None:
    signing_hit: set[int] = set()
    for n in ast.walk(tree):
        pairs: list[tuple[str, ast.AST | None, int]] = []
        if isinstance(n, ast.Assign):
            pairs = [(_target_name(t), n.value, n.lineno) for t in n.targets]
        elif isinstance(n, ast.AnnAssign):
            pairs = [(_target_name(n.target), n.value, n.lineno)]
        elif isinstance(n, ast.Call):
            name = call_name(n)
            if name.endswith(("getenv", "environ.get")) and len(n.args) >= 2:
                env = const_str(n.args[0]) or ""
                # An empty default fails closed in any code that checks it; a non-empty one silently signs with it.
                if SIGNING_NAME.search(env) and const_str(n.args[1]):
                    signing_hit.add(id(n.args[1]))
                    out.append(make(PACK, p, "SEC-002", "high", rel, n.lineno, f"{env} falls back to a literal default",
                                    f"read it with os.environ['{env}'] and refuse to start when it is missing or shorter than 32 chars"))
                    continue
            pairs = [(k.arg or "", k.value, n.lineno) for k in n.keywords]
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = n.args.args[len(n.args.args) - len(n.args.defaults):]
            pairs = [(a.arg, d, n.lineno) for a, d in zip(args, n.args.defaults)]
        elif isinstance(n, ast.Dict):
            pairs = [(const_str(k) or "", v, n.lineno) for k, v in zip(n.keys, n.values) if k is not None]
        for name, value, line in pairs:
            if not name or value is None or id(value) in signing_hit:
                continue
            lit = _default_value(value)
            if lit is None:
                continue
            if SIGNING_NAME.search(name) and not isinstance(n, ast.Dict):
                out.append(make(PACK, p, "SEC-002", "high", rel, line, f"signing secret {name} has a literal value",
                                "load it from the environment with no default; fail at startup if it is unset or weak", secret=lit))
            elif SECRET_NAME.search(name) and _looks_secret(lit):
                # Seed dicts and call keywords are often demo data; assignments and defaults ship as config.
                sev = "medium" if isinstance(n, (ast.Dict, ast.Call)) else "high"
                out.append(make(PACK, p, "SEC-001", sev, rel, line, f"hard-coded credential in {name}",
                                "move the value to an environment variable and document it in .env.example", secret=lit))


def _resolve_local(fn: ast.AST | None, name: str, before: int) -> ast.AST | None:
    best = None
    for n in ast.walk(fn) if fn is not None else []:
        if isinstance(n, ast.Assign) and n.lineno < before and any(_target_name(t) == name for t in n.targets):
            if best is None or n.lineno > best.lineno:
                best = n
    return best.value if best else None


def _is_built_string(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        sides = (node.left, node.right)
        return any(isinstance(s, (ast.JoinedStr, ast.BinOp)) or const_str(s) is not None for s in sides) and \
            not all(const_str(s) is not None for s in sides)
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format" \
        and const_str(node.func.value) is not None


def _sql(p: Project, rel: str, tree: ast.AST, out: list[Finding]) -> None:
    funcs = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not n.args:
            continue
        name = call_name(n)
        last = name.split(".")[-1]
        if not (last in ("execute", "executemany", "executescript", "exec_driver_sql") and "." in name
                or name in ("text", "sqlalchemy.text", "sa.text", "sql.text")):
            continue
        arg = n.args[0]
        built = _is_built_string(arg) and SQL_WORD.search(ast.unparse(arg))
        if not built and isinstance(arg, ast.Name):
            fn = next((f for f in funcs if f.lineno <= n.lineno <= (f.end_lineno or f.lineno)), tree)
            src = _resolve_local(fn, arg.id, n.lineno)
            built = src is not None and _is_built_string(src) and SQL_WORD.search(ast.unparse(src))
        if built:
            out.append(make(PACK, p, "SEC-004", "high", rel, n.lineno, f"SQL built from a formatted string passed to {last}()",
                            "use bound parameters: text(\"... WHERE id = :id\"), {\"id\": value} or the ORM query API"))


def _dangerous(p: Project, rel: str, tree: ast.AST, out: list[Finding]) -> None:
    guarded = _main_guard_nodes(tree)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = call_name(n)
        first = n.args[0] if n.args else None
        literal = first is not None and const_str(first) is not None
        if name in ("eval", "exec") and first is not None and not literal:
            out.append(make(PACK, p, "SEC-005", "high", rel, n.lineno, f"{name}() on a non-literal value",
                            "parse the data instead (json.loads, ast.literal_eval) or use an explicit dispatch table"))
        elif name in ("pickle.load", "pickle.loads", "cPickle.loads", "dill.load", "dill.loads", "marshal.load",
                      "marshal.loads", "shelve.open"):
            out.append(make(PACK, p, "SEC-005", "medium", rel, n.lineno, f"{name}() can execute code from its input",
                            "store data as JSON; never unpickle data that a user can influence"))
        elif name in ("yaml.load", "yaml.load_all", "yaml.unsafe_load", "yaml.full_load"):
            ln = kw(n, "Loader") or (n.args[1] if len(n.args) > 1 else None)
            loader = dotted(ln) if ln is not None else ""
            if name == "yaml.unsafe_load" or name == "yaml.full_load" or not loader.endswith(("SafeLoader", "CSafeLoader", "BaseLoader")):
                out.append(make(PACK, p, "SEC-005", "high", rel, n.lineno, f"{name}() without SafeLoader",
                                "use yaml.safe_load()"))
        elif name.startswith("subprocess.") and (is_true(kw(n, "shell")) or name in ("subprocess.getoutput", "subprocess.getstatusoutput")):
            out.append(make(PACK, p, "SEC-005", "medium" if literal else "high", rel, n.lineno,
                            f"{name}() runs through a shell", "pass an argument list and shell=False"))
        elif name in ("os.system", "os.popen") and first is not None and not literal:
            out.append(make(PACK, p, "SEC-005", "high", rel, n.lineno, f"{name}() with a built command",
                            "use subprocess.run([...], shell=False) with an argument list"))
        elif name == "torch.load" and not is_true(kw(n, "weights_only")):
            out.append(make(PACK, p, "SEC-005", "medium", rel, n.lineno, "torch.load() without weights_only=True",
                            "pass weights_only=True"))
        if name.split(".")[-1] in ("FastAPI", "Starlette", "run") and is_true(kw(n, "debug")):
            out.append(make(PACK, p, "SEC-006", "medium", rel, n.lineno, "debug=True left on",
                            "drive debug from settings and default it to False"))
        if name in ("uvicorn.run", "run") and is_true(kw(n, "reload")) and id(n) not in guarded:
            out.append(make(PACK, p, "SEC-006", "medium", rel, n.lineno, "uvicorn reload=True outside a __main__ guard",
                            "run reload only in local development"))
        if is_true(kw(n, "allow_credentials")):
            origins = kw(n, "allow_origins")
            if isinstance(origins, ast.Name):
                origins = next((a.value for a in getattr(tree, "body", []) if isinstance(a, ast.Assign)
                                and any(_target_name(t) == origins.id for t in a.targets)), origins)
            wild = isinstance(origins, (ast.List, ast.Tuple)) and any(const_str(e) == "*" for e in origins.elts)
            if wild or const_str(kw(n, "allow_origin_regex")) in (".*", "*", "^.*$"):
                out.append(make(PACK, p, "SEC-009", "high", rel, n.lineno, "CORS allows any origin together with credentials",
                                "list the real frontend origins from settings (e.g. CORS_ORIGINS)"))
        if any(k.arg == "verify" and isinstance(k.value, ast.Constant) and k.value.value is False for k in n.keywords) \
                and not name.endswith("jwt.decode"):
            out.append(make(PACK, p, "SEC-018", "high", rel, n.lineno, "TLS certificate verification disabled (verify=False)",
                            "keep verify=True; pass a CA bundle path if the server uses a private CA"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and dotted(n) in ("ssl._create_unverified_context", "ssl.CERT_NONE"):
            out.append(make(PACK, p, "SEC-018", "high", rel, n.lineno, f"{dotted(n)} disables certificate checks",
                            "use ssl.create_default_context()"))
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(_target_name(t).lower() == "debug" for t in targets) and is_true(n.value):
                out.append(make(PACK, p, "SEC-006", "medium", rel, n.lineno, "DEBUG defaults to True",
                                "default it to False and enable it only through the environment"))


def _jwt(p: Project, rel: str, tree: ast.AST, out: list[Finding]) -> None:
    from_jwt = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                and (n.module or "").split(".")[0] in ("jwt", "jose") for a in n.names if a.name == "decode"}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = call_name(n)
        if not (name.endswith("jwt.decode") or name in from_jwt):
            continue
        opts = kw(n, "options")
        off = isinstance(opts, ast.Dict) and any(const_str(k) in ("verify_signature", "verify_exp") and
                                                 isinstance(v, ast.Constant) and v.value is False
                                                 for k, v in zip(opts.keys, opts.values))
        verify = kw(n, "verify")
        algs = kw(n, "algorithms")
        if off or (isinstance(verify, ast.Constant) and verify.value is False):
            out.append(make(PACK, p, "SEC-010", "critical", rel, n.lineno, "JWT decoded with verification turned off",
                            "always verify the signature and expiry"))
        elif algs is None:
            out.append(make(PACK, p, "SEC-010", "high", rel, n.lineno, "jwt.decode() without algorithms=",
                            "pass algorithms=[settings.JWT_ALGORITHM] (a fixed list, e.g. ['HS256'])"))
        elif "none" in ast.unparse(algs).lower().replace("'", " ").replace('"', " ").split() or "get_unverified_header" in ast.unparse(algs):
            out.append(make(PACK, p, "SEC-010", "critical", rel, n.lineno, "JWT algorithm list allows 'none' or comes from the token",
                            "use a fixed server-side list such as ['HS256']"))


def _passwords(p: Project, rel: str, tree: ast.AST, has_hash_lib: bool, out: list[Finding]) -> None:
    funcs = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = call_name(n)
            if re.fullmatch(r"hashlib\.(md5|sha1|sha224|sha256|sha384|sha512|new)", name):
                fn = next((f for f in funcs if f.lineno <= n.lineno <= (f.end_lineno or f.lineno)), None)
                ctx = ast.unparse(n) + " " + (fn.name if fn else "")
                if re.search(r"passw|pwd", ctx, re.I):
                    out.append(make(PACK, p, "SEC-011", "high", rel, n.lineno, f"password hashed with {name}",
                                    "hash passwords with argon2 or bcrypt (passlib / pwdlib), never a bare digest"))
            if name.split(".")[-1] == "CryptContext":
                schemes = kw(n, "schemes")
                weak = [const_str(e) for e in getattr(schemes, "elts", []) if const_str(e) in WEAK_SCHEMES]
                if weak:
                    out.append(make(PACK, p, "SEC-011", "high", rel, n.lineno, f"weak password scheme {weak[0]}",
                                    "use schemes=['argon2'] or ['bcrypt']"))
            if name.split(".")[-1] in ("choice", "choices", "randint", "random", "getrandbits", "randrange") and name.startswith("random."):
                fn = next((f for f in funcs if f.lineno <= n.lineno <= (f.end_lineno or f.lineno)), None)
                if fn and TOKEN_FUNC.search(fn.name):
                    out.append(make(PACK, p, "SEC-019", "medium", rel, n.lineno, f"{name}() used in {fn.name}()",
                                    "use secrets.token_urlsafe() / secrets.choice() for anything security-relevant"))
        if has_hash_lib:
            continue
        if isinstance(n, ast.ClassDef) and any(isinstance(b, (ast.Assign, ast.AnnAssign)) and _target_name(
                b.targets[0] if isinstance(b, ast.Assign) else b.target) == "__tablename__" for b in n.body):
            for b in n.body:
                t = b.targets[0] if isinstance(b, ast.Assign) else (b.target if isinstance(b, ast.AnnAssign) else None)
                if t is not None and _target_name(t).lower() in ("password", "passwd"):
                    out.append(make(PACK, p, "SEC-011", "high", rel, b.lineno, f"{n.name}.password stored without any hashing library in the project",
                                    "keep only an argon2 or bcrypt hash (column password_hash), never the plain value"))
        if isinstance(n, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in n.ops):
            sides = [n.left, *n.comparators]
            if sum(bool(re.search(r"passw", ast.unparse(s), re.I)) for s in sides) >= 2:
                out.append(make(PACK, p, "SEC-011", "high", rel, n.lineno, "password compared as plain text",
                                "verify with the hashing library (pwd_context.verify(plain, user.password_hash))"))


def scan_python(p: Project) -> list[Finding]:
    out: list[Finding] = []
    files = p.python_files()
    has_hash_lib = any(HASH_LIBS.search(p.text(f)) for f in files) or any(
        HASH_LIBS.search(p.text(f)) for f in p.named(r"^requirements.*\.txt$|^pyproject\.toml$"))
    for rel in files:
        tree = p.tree(rel)
        if tree is None:
            continue
        _secrets(p, rel, tree, out)
        _sql(p, rel, tree, out)
        _dangerous(p, rel, tree, out)
        _jwt(p, rel, tree, out)
        _passwords(p, rel, tree, has_hash_lib, out)
    return out
