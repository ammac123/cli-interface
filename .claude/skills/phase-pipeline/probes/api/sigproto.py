import inspect, enum, dataclasses
from pathlib import Path
from typing import Annotated, Literal, get_args, get_origin, get_type_hints, Any, Callable

@dataclasses.dataclass(frozen=True)
class Param:
    label: str | None = None
    help: str = ""
    choices: Any = None          # iterable or zero-arg callable
    secret: bool = False
    validate: Callable[[Any], None] | None = None

@dataclasses.dataclass
class ParamSpec:
    name: str; type: Any; default: Any; meta: Param
    def coerce(self, raw: str):
        t = self.type
        if get_origin(t) is Literal:
            if raw not in map(str, get_args(t)): raise ValueError(f"choose one of {get_args(t)}")
            return next(a for a in get_args(t) if str(a) == raw)
        if isinstance(t, type) and issubclass(t, enum.Enum): return t[raw]
        if t is bool: return raw.strip().lower() in {"1","true","yes","y","on"}
        if t in (int, float, Path, str): return t(raw)
        return raw

def params_of(fn) -> list[ParamSpec]:
    hints = get_type_hints(fn, include_extras=True)
    out = []
    for name, p in inspect.signature(fn).parameters.items():
        if name == "ctx": continue
        t, meta = hints.get(name, str), Param()
        if get_origin(t) is Annotated:
            t, *extras = get_args(t); meta = next((e for e in extras if isinstance(e, Param)), meta)
        out.append(ParamSpec(name, t, None if p.default is p.empty else p.default, meta))
    return out

# foreign function, untouched except optional Annotated metadata
def extract(ctx, filter: Literal["default", "fixed", "variable"] = "default",
            limit: int = 4, headless: bool = True,
            out_dir: Path = Path("~/out"),
            password: Annotated[str, Param(secret=True)] = "") -> list[dict]:
    return [{"filter": filter, "limit": limit}]

for s in params_of(extract):
    print(f"{s.name:9} type={getattr(s.type,'__name__',s.type)!s:40} default={s.default!r:14} secret={s.meta.secret}")
specs = {s.name: s for s in params_of(extract)}
print("coerce limit '7' ->", repr(specs["limit"].coerce("7")), "| filter 'fixed' ->", repr(specs["filter"].coerce("fixed")))
try: specs["filter"].coerce("bogus")
except ValueError as e: print("validation:", e)
