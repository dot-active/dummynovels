#!/usr/bin/env python3
"""
用本地 ComfyUI 一次性生成宣传视频脚本里的全部图片。

脚本会直接读取「宣传视频脚本.md」，找出每个镜头的 ```提示词``` 代码块，
套进你自己的 ComfyUI 工作流，一张张加入 ComfyUI 的队列。

用法（ComfyUI 先启动好，默认地址 http://127.0.0.1:8188）：
    python comfyui_batch.py 宣传视频脚本.md workflow_api.json
    python comfyui_batch.py 宣传视频脚本.md workflow_api.json --only 03,09,12
    python comfyui_batch.py 宣传视频脚本.md --list        # 只列出提示词，不生成

workflow_api.json：在 ComfyUI 里打开你平常出图用的工作流，
菜单「Workflow → Export (API)」（旧版界面：设置里打开 Dev mode 后点「Save (API Format)」）导出。
只需要 Python 3，不用安装任何第三方库。
"""
import argparse, json, re, sys, time, urllib.request, urllib.error, uuid, copy
from pathlib import Path

DEFAULT_NEG = ("text, letters, watermark, logo, signature, gore, blood, corpse, nudity, "
               "cartoon, anime, 3d render, extra fingers, deformed hands")

def parse_md(path):
    """返回 [(镜头编号, 提示词)]，另外把缩略图提示词编号为 thumb。"""
    text = Path(path).read_text(encoding="utf-8")
    shots, current = [], None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^#### 镜头 (\d+)", line)
        if m:
            current = m.group(1)
        elif re.match(r"^## .*缩略图", line):
            current = "thumb"
        elif re.match(r"^## ", line):
            current = None
        stripped = line.lstrip("> ").strip()
        if stripped == "```提示词" and current:
            block = []
            i += 1
            while i < len(lines) and lines[i].lstrip("> ").strip() != "```":
                block.append(lines[i].lstrip("> ").strip() if line.startswith(">") else lines[i])
                i += 1
            prompt = " ".join(b.strip() for b in block if b.strip())
            used = {s[0] for s in shots}
            name = current if current not in used else current + "b"   # 备用提示词，例如 12b
            shots.append((name, prompt))
        i += 1
    neg = DEFAULT_NEG
    m = re.search(r"反向提示词[^\n]*\n\s*```\n\s*(.+?)\n\s*```", text)
    if m:
        neg = m.group(1).strip()
    return shots, neg

def find_text_node(wf, ref, seen=None):
    """从采样器的 positive/negative 输入往上追，找到真正写文字的节点。"""
    seen = seen or set()
    if not isinstance(ref, list) or not ref:
        return None
    nid = str(ref[0])
    if nid in seen or nid not in wf:
        return None
    seen.add(nid)
    inputs = wf[nid].get("inputs", {})
    if any(isinstance(inputs.get(k), str) for k in ("text", "text_g", "text_l", "clip_l", "t5xxl")):
        return nid
    for key in ("conditioning", "conditioning_1", "conditioning_to", "positive", "negative"):
        found = find_text_node(wf, inputs.get(key), seen)
        if found:
            return found
    return None

def locate_nodes(wf):
    pos = neg = None
    for nid, node in wf.items():                      # 1) 先认节点标题
        title = node.get("_meta", {}).get("title", "").strip().upper()
        if title in ("POSITIVE", "正向", "正向提示词"):
            pos = nid
        elif title in ("NEGATIVE", "反向", "反向提示词"):
            neg = nid
    if pos:
        return pos, neg
    for nid, node in wf.items():                      # 2) 再从采样器往上追
        inputs = node.get("inputs", {})
        if "positive" in inputs:
            pos = find_text_node(wf, inputs["positive"])
            neg = find_text_node(wf, inputs.get("negative"))
        elif node.get("class_type", "").endswith("Guider") and "conditioning" in inputs:
            pos = find_text_node(wf, inputs["conditioning"])
        if pos:
            return pos, neg
    return None, None

def set_text(node, value):
    inputs = node["inputs"]
    for k in ("text", "text_g", "text_l", "clip_l", "t5xxl"):
        if isinstance(inputs.get(k), str):
            inputs[k] = value

def build(wf, pos_id, neg_id, prompt, negative, seed, width, height, prefix):
    wf = copy.deepcopy(wf)
    set_text(wf[pos_id], prompt)
    if neg_id and negative is not None:
        set_text(wf[neg_id], negative)
    for node in wf.values():
        inputs = node.get("inputs", {})
        ct = node.get("class_type", "")
        for k in ("seed", "noise_seed"):
            if k in inputs and not isinstance(inputs[k], list):
                inputs[k] = seed
        if "Latent" in ct and "width" in inputs and width:
            inputs["width"], inputs["height"] = width, height
        if ct in ("SaveImage", "Image Save") and "filename_prefix" in inputs:
            inputs["filename_prefix"] = prefix
    return wf

def post(server, wf, client_id):
    data = json.dumps({"prompt": wf, "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(server.rstrip("/") + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["prompt_id"]

def main():
    ap = argparse.ArgumentParser(description="用 ComfyUI 批量生成宣传视频脚本里的图片")
    ap.add_argument("script_md", help="宣传视频脚本.md")
    ap.add_argument("workflow", nargs="?", help="从 ComfyUI 导出的 API 格式工作流 JSON")
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--width", type=int, default=1344, help="默认 1344（16:9）")
    ap.add_argument("--height", type=int, default=768, help="默认 768（16:9）")
    ap.add_argument("--seed", type=int, default=20261126, help="起始种子，每张图 +1")
    ap.add_argument("--batch", type=int, default=1, help="每个镜头生成几张候选（默认 1）")
    ap.add_argument("--only", help="只生成这些镜头，例如 03,09,thumb")
    ap.add_argument("--prefix", help="输出文件名前缀，默认用小说文件夹名")
    ap.add_argument("--no-negative", action="store_true", help="不改动工作流里的反向提示词")
    ap.add_argument("--list", action="store_true", help="只列出提示词，不生成")
    a = ap.parse_args()

    shots, negative = parse_md(a.script_md)
    if a.only:
        want = {x.strip() for x in a.only.split(",")}
        shots = [s for s in shots if s[0] in want]
    if not shots:
        sys.exit("没有找到任何提示词。")
    if a.list or not a.workflow:
        for name, p in shots:
            print(f"[{name}] {p}\n")
        print(f"共 {len(shots)} 段提示词。反向提示词：{negative}")
        return

    wf = json.loads(Path(a.workflow).read_text(encoding="utf-8"))
    if "nodes" in wf and "links" in wf:
        sys.exit("这个 JSON 是普通工作流格式。请在 ComfyUI 里用「Export (API)」/「Save (API Format)」重新导出。")
    pos_id, neg_id = locate_nodes(wf)
    if not pos_id:
        sys.exit("找不到正向提示词节点。请把它的标题改成 POSITIVE（反向的改成 NEGATIVE）后重新导出。")
    print(f"正向提示词节点：{pos_id}　反向提示词节点：{neg_id or '（没有）'}")

    prefix = a.prefix or Path(a.script_md).resolve().parent.name
    client_id = str(uuid.uuid4())
    n = 0
    for name, prompt in shots:
        base = int(re.sub(r"\D", "", name) or 99) * 100 + (50 if name.endswith("b") else 0)
        for k in range(a.batch):
            seed = a.seed + base + k          # 种子只跟镜头编号有关：单独重跑某个镜头也能得到同一张图
            job = build(wf, pos_id, neg_id, prompt, None if a.no_negative else negative,
                        seed, a.width, a.height, f"{prefix}/{name}")
            try:
                pid = post(a.server, job, client_id)
            except urllib.error.HTTPError as e:
                sys.exit(f"ComfyUI 拒绝了镜头 {name}：{e.read().decode('utf-8', 'replace')[:500]}")
            except urllib.error.URLError as e:
                sys.exit(f"连不上 ComfyUI（{a.server}）：{e.reason}。请先启动 ComfyUI。")
            n += 1
            print(f"已加入队列：镜头 {name}（种子 {seed}）")
            time.sleep(0.05)
    print(f"\n全部 {n} 张已加入 ComfyUI 队列。图片会存到 ComfyUI 的 output/{prefix}/ 文件夹，"
          f"文件名以镜头编号开头（例如 01_00001_.png）。")

if __name__ == "__main__":
    main()
