#!/usr/bin/env python3
"""把 Orrery 的一个切片和协议语料发布到目标仓库。

    python3 release/usenix/anonymous_release.py           # dry-run，只打印会发生什么
    python3 release/usenix/anonymous_release.py --apply   # 真正落盘
    python3 release/usenix/anonymous_release.py scan <语料库>   # 生成可粘贴的两段

配置只有一份 anonymous.toml，所以主命令一个参数都不带。流程是拷贝 -> 正文替换 ->
门禁 -> 同步：前三步都在临时暂存区里做，门禁不通过则目标仓库一个字节都不会被碰。

发布只做拷贝、扣留和门禁，不改写源码正文——源码里的话本身就得是对的。拷贝、删除、
扫描全部用标准库实现，不外调 rsync，行为不随平台变。
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 扣留标记只有一个，两条发布路径共用同一个可 grep 的串。
sys.path.insert(0, str(HERE))
from latest_3_to_remove_sensitive_open import WITHHELD_TAG        # noqa: E402


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

def load_config() -> dict:
    """anonymous.toml 是全部配置；identity.toml 单列，因为 open_to_thin.py 也读它。"""
    cfg: dict = {}
    for name in ("anonymous.toml", "identity.toml"):
        path = HERE / name
        if not path.is_file():
            die(f"缺少配置: {path}")
        with path.open("rb") as f:
            cfg.update(tomllib.load(f))
    # 迁移源就是这份工具所在的仓库，从 __file__ 推出来，配置里不写本机路径。
    cfg.setdefault("src", str(HERE.parents[1]))
    return cfg


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(2)


class Excluder:
    """按名字匹配的垃圾过滤，任意层级都生效（等价于 rsync --exclude=NAME）。"""

    def __init__(self, patterns: list[str]):
        self.patterns = patterns

    def hit(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, p) for p in self.patterns)


def path_excluded(rel: str, patterns: list[str]) -> bool:
    """路径级排除：pattern 命中它自己和它底下的一切，相对拷贝源的根来写。

    支持通配，且 fnmatch 的 * 会跨 /，`ISO/*/source` 连 `ISO/a/b/source` 一起挡。
    """
    parts = rel.split("/")
    ancestors = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    for p in patterns:
        p = p.strip("/")
        if any(a == p or fnmatch.fnmatch(a, p) for a in ancestors):
            return True
    return False


def withheld(rel: str, rules: list[dict]) -> bool:
    """版权文档:under 命中的目录底下,除 keep 列的文件名外一律不拷。

    文件级判据,不能拿去剪枝目录——`source/` 本身还得走进去才能把 README 捡出来。
    默认扣下、白名单放行,语料里新冒出来的文档格式不改规则就已经挡住。
    """
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")[:-1]
    dirs = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    for rule in rules:
        under = rule["under"].strip("/")
        if not any(d == under or fnmatch.fnmatch(d, under) for d in dirs):
            continue
        if not any(fnmatch.fnmatch(name, k) for k in rule.get("keep", [])):
            return True
    return False


# --------------------------------------------------------------------------
# 1. 拷贝
# --------------------------------------------------------------------------

def copy_entry(src_root: Path, rel: str, dst_root: Path, excl: Excluder,
               path_excl: list[str], wh: list[dict] | None = None) -> int:
    """把 src_root/rel 整个拷到 dst_root/rel，保住 rel 自己的层级，返回文件数。

    白名单条目写错就是漏发，所以路径不存在直接失败，不静默跳过；符号链接一律拒绝，
    跟不跟随都会让发布结果依赖本机布局。
    """
    src = src_root / rel
    if not src.exists():
        die(f"白名单里的路径在源里不存在: {rel}  (源: {src_root})")
    if src.is_symlink():
        die(f"拒绝拷贝符号链接: {rel}  (跟不跟随都会让发布结果依赖本机布局)")

    if src.is_file():
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1

    count = 0
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        here = Path(dirpath)
        # 就地改 dirnames 才能真正剪枝，被排除的目录不再走进去。
        dirnames[:] = sorted(
            d for d in dirnames
            if not excl.hit(d)
            and not path_excluded(rel_of(here / d, src_root), path_excl)
        )
        for name in sorted(filenames):
            if excl.hit(name):
                continue
            f = here / name
            if f.is_symlink():
                die(f"拒绝拷贝符号链接: {rel_of(f, src_root)}")
            f_rel = rel_of(f, src_root)
            if path_excluded(f_rel, path_excl) or withheld(f_rel, wh or []):
                continue
            dst = dst_root / rel_of(f, src_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            count += 1
    return count


def rel_of(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def stage_all(cfg: dict, stage: Path, excl: Excluder) -> None:
    print("==> 拷贝")
    src = Path(cfg["src"])
    # 顶层 copy 也要能按路径排除：experiments/ 下的 config.yaml 带着活的 api_key，
    # 而 runs/ 底下的同名文件是要发的产物快照，按名字挡会把证据一起挡掉。语义与
    # [[lib]].exclude 相同：相对 src 根，命中它自己和它底下的一切。
    src_excl = cfg.get("exclude_paths", [])
    for rel in cfg["copy"]:
        n = copy_entry(src, rel, stage, excl, src_excl)
        print(f"    {rel}  ({n} 个文件)")

    for lib in cfg.get("lib", []):
        lib_src = Path(lib["src"])
        if not lib_src.is_dir():
            die(f"语料库不存在: {lib_src}")
        lib_dst = stage / lib["dest"]
        lib_excl = lib.get("exclude", [])
        for rel in lib["copy"]:
            n = copy_entry(lib_src, rel, lib_dst, excl, lib_excl,
                           lib.get("withhold", []))
            landed = lib_dst / rel
            if not landed.exists():
                die(f"拷贝落位错误: 期望 {lib['dest']}/{rel}")
            print(f"    {lib['dest']}/{rel}  ({n} 个文件)")

    # 发布层自己写的文档，讲的是这一次发布做了哪些取舍，源码里放在做出取舍的配置旁边。
    for ov in cfg.get("overlay", []):
        src_f = HERE / ov["from"]
        if not src_f.is_file():
            die(f"overlay 源不存在: {src_f}")
        dst_f = stage / ov["to"]
        dst_f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_f, dst_f)
        print(f"    [overlay] {ov['to']}")

    print(f"    共 {len(list(walk_files(stage)))} 个文件")


def walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


# --------------------------------------------------------------------------
# 1b. 正文替换
# --------------------------------------------------------------------------

#: YAML frontmatter 与正文的分界；frontmatter 是 loader 要解析的结构，正文才是散文。
_FRONTMATTER = re.compile(r"\A(---\n.*?\n---\n)", re.S)


def replace_bodies(stage: Path, rules: list[dict], dest_name: str) -> None:
    """把命中规则的语料文件正文换成扣留说明，frontmatter 原样留下。

    扣下的是正文不是文件：`subprotocol.md` 的正文会被 `loader.py` 读进每个抽取节点
    的提示词，整份删掉重跑时就少一句范围说明，换掉正文则 frontmatter 与说明都保住。
    一条规则命中 0 次即中止发布，空匹配当成功就是下一次原文照发。
    """
    if not rules:
        return
    print("==> 正文替换")
    hit = 0
    for rule in rules:
        under = rule["under"].strip("/")
        match = rule["match"]
        why = rule["why"]
        for f in walk_files(stage):
            rel = rel_of(f, stage)
            if not rel.startswith(dest_name + "/"):
                continue
            inner = rel[len(dest_name) + 1:]
            parts = inner.split("/")[:-1]
            dirs = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
            if not any(d == under or fnmatch.fnmatch(d, under) for d in dirs):
                continue
            if not fnmatch.fnmatch(inner.rsplit("/", 1)[-1], match):
                continue
            text = f.read_text(encoding="utf-8")
            keep = (m.group(1) if (m := _FRONTMATTER.search(text)) else "")
            f.write_text(keep + withheld_body(inner, why), encoding="utf-8")
            hit += 1
            print(f"    {rel}")
    if not hit:
        die("[[lib.replace]] 一条也没命中：规则写错了，还是语料改了布局？"
            "空匹配当成功，就是下一次原文照发。")


def withheld_body(unit_rel: str, why: str) -> str:
    """站在被扣下的正文那里的说明。

    措辞和 `latest_3_to_remove_sensitive_open.py::withheld_note` 同一套，读的人在
    runs/ 里和在语料里见到的是同一句话。取回路径指向标准那一级的 `source/README.md`，
    目录号、版次、取回方式都在那，且那份 README 是发出去的。
    """
    home = unit_rel.split("/subprotocols/")[0]
    return (
        "\n"
        f"{WITHHELD_TAG}\n"
        "\n"
        "This description quoted the specification's own clause text — a\n"
        "block quotation of the clause this sub-protocol narrows, and several\n"
        "phrases from it — so it is withheld for copyright reasons. It was not\n"
        "lost or truncated by the packaging.\n"
        "\n"
        f"{why}\n"
        "\n"
        "What stood here said which branch of the clause this target models:\n"
        "the optional field it leaves out, and what the verifier therefore\n"
        "does not check. The sibling target under the same standard models the\n"
        "other branch, and the two directory names say which is which.\n"
        "\n"
        f"To read the clause, obtain the document from its publisher.\n"
        f"`{home}/source/README.md` records this document's catalogue entry,\n"
        "its edition and the retrieval route.\n"
        "\n"
        "Everything else about this target is here unchanged: its principals,\n"
        "its flow model, its declared setups and its verdicts.\n"
    )


# --------------------------------------------------------------------------
# 2. 门禁
# --------------------------------------------------------------------------

def gate(stage: Path, patterns: list[str]) -> None:
    """在暂存区里扫敏感串，命中即中止——此刻目标仓库还没被碰过。

    内容和路径分开扫：整条路径里的泄漏、文件名里带敏感词的，只扫内容都抓不到。
    二进制按 latin-1 解，字节到字符一一对应不会抛异常，相当于 grep 扫其中的
    ASCII 串。
    """
    print("==> 门禁")
    files = list(walk_files(stage))
    paths = [rel_of(f, stage) for f in files]
    fail = False
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)

        hits = []
        for f, rel in zip(files, paths):
            text = f.read_bytes().decode("latin-1")
            for line in text.splitlines():
                if rx.search(line):
                    hits.append(f"{rel}: {line.strip()[:120]}")
                    if len(hits) >= 10:
                        break
            if len(hits) >= 10:
                break
        if hits:
            fail = True
            print(f"    命中内容 [{pat}]", file=sys.stderr)
            for h in hits:
                print(f"      {h}", file=sys.stderr)

        path_hits = [p for p in paths if rx.search(p)][:10]
        if path_hits:
            fail = True
            print(f"    命中路径 [{pat}]", file=sys.stderr)
            for p in path_hits:
                print(f"      {p}", file=sys.stderr)

    if fail:
        die("发布中止，目标仓库未改动。")
    print("    通过")


# --------------------------------------------------------------------------
# 3. 同步
# --------------------------------------------------------------------------

def is_protected(rel: str, patterns: list[str]) -> bool:
    """目标仓库自有、不归本次同步管辖的路径。

    一条 protect 同时表达不被覆盖和不被删，锚定在仓库根，末尾带 / 表示整棵子树。
    """
    for p in patterns:
        p = p.lstrip("/")
        if p.endswith("/"):
            base = p.rstrip("/")
            if rel == base or rel.startswith(base + "/"):
                return True
        elif fnmatch.fnmatch(rel, p) or rel.startswith(p + "/"):
            return True
    return False


def sync(stage: Path, dest: Path, protect: list[str], apply: bool) -> None:
    protect = list(protect) + [".git/"]

    staged = {rel_of(f, stage): f for f in walk_files(stage)}
    if not staged:
        die("暂存区为空，拒绝同步")

    existing = {}
    for dirpath, dirnames, filenames in os.walk(dest, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in sorted(dirnames)
            if not is_protected(rel_of(here / d, dest), protect)
        ]
        for name in sorted(filenames):
            rel = rel_of(here / name, dest)
            if not is_protected(rel, protect):
                existing[rel] = here / name

    writes, skips = [], []
    for rel, src in staged.items():
        if is_protected(rel, protect):
            skips.append(rel)
            continue
        dst = dest / rel
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            writes.append(rel)
    deletes = sorted(set(existing) - set(staged))

    print(f"==> 同步到 {dest}{'  [落盘]' if apply else ''}")
    print(f"    写入 {len(writes)} 项，删除 {len(deletes)} 项"
          f"{f'，跳过 {len(skips)} 项（protect）' if skips else ''}")
    if deletes:
        print("    删除分布（顶层 / 条数）：")
        buckets: dict[str, int] = {}
        for rel in deletes:
            key = "/".join(rel.split("/")[:2])
            buckets[key] = buckets.get(key, 0) + 1
        for key, n in sorted(buckets.items(), key=lambda kv: -kv[1])[:15]:
            print(f"      {n:>5}  {key}")

    if not apply:
        return

    for rel in writes:
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged[rel], dst)
    for rel in deletes:
        (dest / rel).unlink()
    prune_empty_dirs(dest, protect)


def prune_empty_dirs(dest: Path, protect: list[str]) -> None:
    """删文件会留下空目录，自底向上收一遍；protect 的子树整个不动。"""
    for dirpath, dirnames, filenames in sorted(
        os.walk(dest, topdown=False, followlinks=False), reverse=True
    ):
        here = Path(dirpath)
        if here == dest:
            continue
        rel = rel_of(here, dest)
        if is_protected(rel, protect):
            continue
        if not any(here.iterdir()):
            here.rmdir()


# --------------------------------------------------------------------------
# 发布
# --------------------------------------------------------------------------

def do_release(apply: bool, keep_stage: bool = False) -> None:
    cfg = load_config()
    src, dest = Path(cfg["src"]), Path(cfg["dest"])

    # 唯一的致命事故是 dest 被写成源路径：下面的删除会反向清空它。
    for label, p in (("src", src), ("dest", dest)):
        if not p.is_absolute():
            die(f"{label} 必须是绝对路径: {p}")
        if not p.is_dir():
            die(f"{label} 不存在: {p}")
    if src.resolve() == dest.resolve():
        die("拒绝执行：src 与 dest 是同一个目录")
    for lib in cfg.get("lib", []):
        if Path(lib["src"]).resolve() == dest.resolve():
            die("拒绝执行：语料库与 dest 是同一个目录")

    excl = Excluder(cfg["exclude"])
    stage_root = Path(tempfile.mkdtemp(prefix="aif-release-"))
    stage = stage_root / "stage"
    stage.mkdir()
    try:
        stage_all(cfg, stage, excl)
        for lib in cfg.get("lib", []):
            replace_bodies(stage, lib.get("replace", []), lib["dest"])
        gate(stage, cfg["sensitive"])
        sync(stage, dest, cfg.get("protect", []), apply)
    finally:
        if keep_stage:
            # 门禁是机器判据，暂存区留下来供人工翻一遍。
            print(f"    暂存区保留在 {stage}")
        else:
            shutil.rmtree(stage_root, ignore_errors=True)

    if not apply:
        print()
        print("以上是 dry-run。确认无误后加 --apply 落盘。")
        return

    # 目标仓库的提交身份：不设置就取全局身份，git log 里会出现真实姓名和邮箱。
    git = cfg["git"]
    subprocess.run(["git", "-C", str(dest), "config", "user.name", git["name"]], check=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.email", git["email"]], check=True)
    print()
    print(f"已落盘。目标仓库的提交身份已设为 {git['name']} <{git['email']}>。")
    print(f"接下来在 {dest} 里检查 git status 并自行提交。")


# --------------------------------------------------------------------------
# 扫语料库：生成白名单
# --------------------------------------------------------------------------

def is_unit(d: Path, excl: Excluder) -> bool:
    """一个目录算一个单元，当且仅当它自己有 claims/claims.json。

    判据要和论文的 libUnits 宏、experiments/reproduce.py 一致，三处才对得上，
    否则白名单会漏发论文报了的东西。不看 formal/：ISO/9798-2 的
    mechanism-{2,4}-no-identifier 没有自己的参考 ProVerif 模型，仍是真单元。"""
    return (d / "claims" / "claims.json").is_file()


def pad(entry: str, width: int = 58) -> str:
    """对齐注释列；条目本身超宽时也留一个空格，不能和 # 粘在一起。"""
    return entry.ljust(width) if len(entry) < width else entry + "  "


def do_scan(corpus: Path) -> None:
    excl = Excluder(load_config()["exclude"])
    if not corpus.is_dir():
        die(f"语料库不存在: {corpus}")

    units = sorted(
        rel_of(Path(dirpath), corpus)
        for dirpath, dirnames, _ in os.walk(corpus, followlinks=False)
        if not any(excl.hit(part) for part in Path(dirpath).parts)
        and is_unit(Path(dirpath), excl)
    )

    # 单元不等于拷贝根：子协议布局下 source/ 和 annotations/ 共享在版本层，
    # 只拷 subprotocols/<sub>/ 会丢掉输入，所以拷贝根取版本层。
    roots = sorted({
        str(Path(u).parent.parent.as_posix()) if Path(u).parent.name == "subprotocols" else u
        for u in units
    })
    # 真出现嵌套（根 A 在根 B 底下）时只留最外层，免得同一份文件拷两次。
    roots = [r for r in roots if not any(r.startswith(o + "/") for o in roots if o != r)]

    print("# 扫描判据：自己有 formal/ 代码 且 有 claims/*.json。")
    print("# 输出是给人过目、再落到 profile 里的——不在发布时动态求值：语料库天天在长，")
    print("# 动态判据意味着新协议一达标就自动外发，而白名单要的正是「改一行才发」。")
    print()
    print("copy = [")
    for r in roots:
        n = sum(1 for u in units if u == r or u.startswith(r + "/"))
        print(pad(f'  "{r}",') + f"# {n} 个单元")
    print("]")
    print()

    print("exclude = [")
    for r in roots:
        subs = corpus / r / "subprotocols"
        if not subs.is_dir():
            continue
        for sub in sorted(p for p in subs.iterdir() if p.is_dir()):
            rel = rel_of(sub, corpus)
            if rel in units:
                continue
            why = "缺 claims json" if (sub / "formal").is_dir() else "缺 formal 代码"
            print(pad(f'  "{rel}",') + f"# {why}")
    print("]")
    print()

    # 白名单是整目录拷走，单元判据只挑目录；两者之间的缝要主动报出来。
    print("# 随拷贝根搭车、本身不是合格单元的 formal/：")
    for r in roots:
        for dirpath, _, _ in os.walk(corpus / r, followlinks=False):
            d = Path(dirpath)
            if d.name != "formal":
                continue
            u = rel_of(d.parent, corpus)
            if u in units or d.parent.parent.name == "subprotocols":
                continue
            print(f"#   {u}")
    print()

    # 漏发和有意不发，在输出里必须能分辨。
    print("# 整条没进白名单的目录（有 formal 或 claims，但不成对）：")
    for dirpath, _, _ in os.walk(corpus, followlinks=False):
        d = Path(dirpath)
        if d.name not in ("formal", "claims"):
            continue
        u = rel_of(d.parent, corpus)
        if u in units or any(u == r or u.startswith(r + "/") for r in roots):
            continue
        print(f"#   {u}")


# --------------------------------------------------------------------------

def main() -> None:
    # scan 单独挑出来手工分派：它带一个位置参数，而主命令一个都不带。
    argv = sys.argv[1:]
    if argv and argv[0] == "scan":
        ap = argparse.ArgumentParser(prog="anonymous_release.py scan",
                                     description="扫语料库，生成可粘贴的 copy / exclude 两段")
        ap.add_argument("corpus", type=Path, help="语料库根目录")
        do_scan(ap.parse_args(argv[1:]).corpus)
        return

    ap = argparse.ArgumentParser(
        prog="anonymous_release.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--apply", action="store_true", help="真正落盘；不加就是 dry-run")
    ap.add_argument("--keep-stage", action="store_true",
                    help="不删暂存区，打印路径供人工核对")
    args = ap.parse_args(argv)
    do_release(args.apply, args.keep_stage)


if __name__ == "__main__":
    main()
