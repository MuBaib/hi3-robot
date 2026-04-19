import json
import os
import sys
import asyncio
import aiohttp
import time
import threading
import subprocess
import zipfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta, date
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, Checkbutton, IntVar
from tkinter import simpledialog as sd
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ====================== 全局配置（融合两个脚本所有配置） ======================
# 配置查询机器人核心配置
CONFIG = {
    "WS_URL": "ws://127.0.0.1:3066/ws",
    "BOT_QQ": "2118238474",
    "SAVE_FOLDER": "./robot_data",
    "JSON_FOLDER": "./json_data",
    "FILE_NAME": "AvatarConfig.json",
    "is_running": False,
    "ws_session": None
}
# AB包/战场深渊/ZIP/文件搜索配置
CLI_PATH        = ""
ALLOW_SUFFIX    = {".ab", ".unity3d", ".assets"}
CLI_EXTRA_ARGS  = ["--game", "BH3", "--types", "Texture2D", "--silent"]
CONFIG_FILE = "bh3_bot_config.json"
FILE_FOLDER = ""
ALLOW_GROUPS = []
watch_folders = []
export_folder = ""
EXPORT_NOTIFY_GROUPS = []
AUTO_SEND_EXPORT_FILE = True
# 战场深渊配置
ABYSS_BATTLEFIELD_NOTIFY_GROUPS = []
ABYSS_BATTLEFIELD_WATCH_FOLDERS = []
ABYSS_BATTLEFIELD_ALLOW_SUFFIX = {".json"}
ABYSS_BATTLEFIELD_REQUIRED_FILES = {
    "abyss": ["UltraEndlessBattleConfig.json", "StageDetail_Monster.json", "UltraEndlessBuff.json"],
    "battlefield": ["ExBossMonsterSchedule.json", "ExBossMonsterData.json", "UniqueMonsterData.json"]
}
ABYSS_BATTLEFIELD_DEBOUNCE_TIME = 5
last_process_time = {}
# ZIP解压配置
ZIP_WATCH_FOLDERS = []
ZIP_EXTRACT_PATH = ""
ZIP_NOTIFY_GROUPS = []
ZIP_ALLOW_SUFFIX = {".zip"}
zip_old_files = set()
zip_observer = None
ZIP_DEBOUNCE_TIME = 3
zip_last_process_time = {}
# 完成报告通知群配置
REPORT_GROUPS = []
# ====================== ✅ 新增：三合一解析工具 独立全局变量 ======================
tri_processed = set()
tri_monitor_running = False
tri_watch_path = ""
tri_out_path = ""
# 通用全局变量
old_files = set()
abyss_battlefield_old_files = set()
observer = None
abyss_battlefield_observer = None
zip_observer = None
LISTEN_THREAD = None
IS_RUNNING = False
EXPORT_FILE_MAP = {}
# 已发送文件去重
SENT_FILE_RECORD = "sent_files.json"
sent_files = set()
# ====================== 通用工具函数（去重融合） ======================
log_box = None
def log(msg):
    """统一日志输出（修复NoneType错误）"""
    global log_box
    try:
        if log_box:
            log_box.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            log_box.see(tk.END)
            log_box.update()
        else:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def load_sent_files():
    """加载已发送文件记录"""
    global sent_files
    if os.path.exists(SENT_FILE_RECORD):
        try:
            with open(SENT_FILE_RECORD, "r", encoding="utf-8") as f:
                sent_files = set(json.load(f))
        except:
            sent_files = set()

def save_sent_file(filepath):
    """保存已发送文件记录"""
    sent_files.add(filepath)
    try:
        with open(SENT_FILE_RECORD, "w", encoding="utf-8") as f:
            json.dump(list(sent_files), f, ensure_ascii=True, indent=2)
    except:
        pass

def run_async_task(coro):
    """统一异步任务执行"""
    if IS_RUNNING or CONFIG["is_running"]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
        loop.close()

# ====================== 新增：统一完成报告发送函数 ======================
async def send_task_finish_report(task_name: str, detail: str):
    """发送功能完成报告到指定群"""
    if not REPORT_GROUPS:
        return
    report_msg = (
        f"📊 崩坏3机器人任务完成报告\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"任务类型：{task_name}\n"
        f"完成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"任务详情：{detail}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    for group_id in REPORT_GROUPS:
        await send_ws("send_group_msg", {"group_id": group_id, "message": report_msg})
        await asyncio.sleep(0.3)

def notify_task_finish(task_name: str, detail: str):
    """触发任务完成报告（同步调用）"""
    run_async_task(send_task_finish_report(task_name, detail))

# ====================== ✅ 新增：三合一JSON解析工具 核心函数 ======================
def flatten_items(data):
    result = []
    if isinstance(data, list):
        for item in data:
            result.extend(flatten_items(item))
    elif isinstance(data, dict):
        result.append(data)
    return result

# 角色解析
attr_map = {
    1: "世界之星", 2: "无存之仪", 3: "命运之轮", 4: "升变之理", 5: "天衍之杯"
}
def parse_character(data):
    return {
        "avatarID": data.get("avatarID"),
        "fullName": data.get("fullName", {}).get("Hash"),
        "AstraRingAttribute": data.get("AstraRingAttribute"),
        "AstraRingAttribute_Name": attr_map.get(data.get("AstraRingAttribute"), "未知"),
        "AstraRingNameTextmapID": data.get("AstraRingNameTextmapID", {}).get("Hash"),
        "LaunchVersion": data.get("LaunchVersion"),
        "skills": [
            {
                "skill_id": skill.get("skillId"),
                "skill_name": skill.get("name"),
                "skill_info": skill.get("info"),
                "sub_skills": [
                    {
                        "sub_skill_id": sub.get("avatarSubSkillId"),
                        "sub_skill_name": sub.get("name"),
                        "sub_skill_info": sub.get("info")
                    } for sub in skill.get("subSkills", [])
                ]
            } for skill in data.get("skillList", [])
        ]
    }

# 圣痕解析
def parse_stigmata(data):
    stig_list = []
    for stig in data.get("圣痕列表", []):
        new_stig = {
            "stigmataMainID": stig.get("stigmataMainID"),
            "StigMateName": stig.get("名称"),
            "LevelAttribute": {}
        }
        lv_attr = stig.get("等级属性", {})
        for lv, attr in lv_attr.items():
            new_stig["LevelAttribute"][lv] = {
                "Atk": attr.get("攻击", 0),
                "HP": attr.get("生命", 0),
                "Defense": attr.get("防御", 0),
                "CriticalHit": attr.get("会心", 0),
                "StigmateSkillName": attr.get("单件技能名称"),
                "StigmateDesc": attr.get("单件技能效果")
            }
        stig_list.append(new_stig)
    return {
        "setID": data.get("setID"),
        "SetName": data.get("套装名"),
        "StigMateList": stig_list,
        "TwoSSN": data.get("2件套技能名称"),
        "TwoSSD": data.get("2件套效果"),
        "ThreeSSN": data.get("3件套技能名称"),
        "ThreeSSD": data.get("3件套效果")
    }

# 武器解析
def parse_weapon(full_data):
    output = []
    for weapon_name, weapon_info in full_data.items():
        w_list = weapon_info.get("武器列表", [])
        if not w_list:
            continue
        weapon_data = {
            "weaponMainID": w_list[0].get("weaponMainID"),
            "WeaponName": weapon_name,
            "WeaponStory": weapon_info.get("武器故事", ""),
            "Levels": {}
        }
        for w in w_list:
            lv = str(w.get("maxLv"))
            weapon_data["Levels"][lv] = {
                "WeaponID": w.get("武器ID"),
                "Atk": w.get("攻击"),
                "CriticalHit": w.get("会心"),
                "ActiveSkillName": w.get("武器主动技能名称"),
                "ActiveSkillDesc": w.get("武器主动技能效果"),
                "Passive1Name": w.get("武器被动1技能名称"),
                "Passive1Desc": w.get("武器被动1技能效果"),
                "Passive2Name": w.get("武器被动2技能名称"),
                "Passive2Desc": w.get("武器被动2技能效果"),
                "SynergySkillName": w.get("同调技能技能名称"),
                "SynergySkillDesc": w.get("同调技能技能效果")
            }
        output.append(weapon_data)
    return output

# 自动分发处理
def process_file_auto(input_path, output_path):
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        log(f"❌ 三合一解析失败：{input_path}（JSON读取错误）")
        return
    data_list = flatten_items(data)
    final = []
    fname = os.path.basename(input_path).lower()
    for item in data_list:
        try:
            if "角色" in fname or "avatar" in fname or ("skillList" in item and "avatarID" in item):
                final.append(parse_character(item))
            elif "圣痕" in fname or "setID" in item or "圣痕列表" in item:
                final.append(parse_stigmata(item))
            elif "武器" in fname or "武器列表" in item:
                if isinstance(item, dict):
                    final.extend(parse_weapon(item))
        except:
            continue
    os.makedirs(output_path, exist_ok=True)
    out_name = os.path.splitext(os.path.basename(input_path))[0] + "_导出.json"
    out_full = os.path.join(output_path, out_name)
    try:
        with open(out_full, "w", encoding="utf-8") as f:
            json.dump(final, f, ensure_ascii=False, indent=4)
        log(f"✅ 三合一解析完成：{out_name}")
        # 发送完成报告
        notify_task_finish("三合一JSON解析", f"文件：{os.path.basename(input_path)} -> {out_name}")
    except:
        log(f"❌ 三合一保存失败：{out_name}")

# 文件夹监控
def tri_monitor_folder():
    global tri_monitor_running, tri_watch_path, tri_out_path
    while tri_monitor_running:
        try:
            for fn in os.listdir(tri_watch_path):
                fp = os.path.join(tri_watch_path, fn)
                if not os.path.isfile(fp):
                    continue
                if not fn.lower().endswith(".json"):
                    continue
                if fp in tri_processed:
                    continue
                tri_processed.add(fp)
                log(f"🔍 三合一检测到新文件：{fn}")
                process_file_auto(fp, tri_out_path)
        except:
            pass
        time.sleep(1)

# 三合一启动/停止
def tri_start_monitor(entry_watch, entry_out, btn_start):
    global tri_monitor_running, tri_watch_path, tri_out_path
    wd = entry_watch.get().strip()
    od = entry_out.get().strip()
    if not wd or not od:
        messagebox.showwarning("提示", "请先选择监控文件夹和导出文件夹！")
        return
    if tri_monitor_running:
        messagebox.showinfo("提示", "三合一监控已在运行中")
        return
    tri_watch_path = wd
    tri_out_path = od
    tri_monitor_running = True
    threading.Thread(target=tri_monitor_folder, daemon=True).start()
    btn_start.config(state=tk.DISABLED, text="监控中...")
    log(f"🚀 三合一监控启动：监控={wd} | 导出={od}")
    messagebox.showinfo("启动成功", "三合一JSON解析监控已启动")

def tri_stop_monitor(btn_start):
    global tri_monitor_running
    if not tri_monitor_running:
        messagebox.showinfo("提示", "三合一监控未运行")
        return
    tri_monitor_running = False
    btn_start.config(state=tk.NORMAL, text="开始监控")
    log("🛑 三合一监控已停止")
    messagebox.showinfo("停止成功", "三合一JSON解析监控已停止")

# ====================== 配置查询机器人 - 配置读写函数 ======================
def load_config_query():
    """加载配置查询数据"""
    file_path = Path(CONFIG["SAVE_FOLDER"]) / CONFIG["FILE_NAME"]
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        messagebox.showerror("加载失败", f"加载配置失败: {e}")
        return []

def save_config_query(data):
    """保存配置查询数据"""
    file_path = Path(CONFIG["SAVE_FOLDER"]) / CONFIG["FILE_NAME"]
    try:
        Path(CONFIG["SAVE_FOLDER"]).mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        messagebox.showerror("保存失败", f"保存配置失败: {e}")

def search_by_field(type_name, field, target_id):
    """JSON文件查询"""
    matched_files = []
    json_folder = Path(CONFIG["JSON_FOLDER"])
    if not json_folder.exists():
        messagebox.showwarning("目录不存在", f"JSON目录 {json_folder} 不存在！")
        return []
    for f in os.listdir(json_folder):
        if f.lower().endswith(".json") and type_name in f:
            matched_files.append(json_folder / f)
    result = []
    target_id = str(target_id).strip()
    for fp in matched_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                jd = json.load(f)
            items = jd if isinstance(jd, list) else [jd]
            for item in items:
                val = str(item.get(field, "")).strip()
                if val == target_id:
                    result.append(item)
        except Exception as e:
            log(f"读取{fp}失败: {e}")
            continue
    return result

# ====================== 配置查询机器人 - 消息解析/指令处理 ======================
def parse_message_segments(message_segments):
    """解析消息段"""
    is_at_bot = False
    cmd_text = ""
    if isinstance(message_segments, str):
        try:
            msg_str = message_segments.replace("'", "\"")
            message_segments = json.loads(msg_str)
        except (json.JSONDecodeError, SyntaxError):
            return is_at_bot, cmd_text
    elif not isinstance(message_segments, list):
        return is_at_bot, cmd_text
    for seg in message_segments:
        seg_type = seg.get("type", "")
        seg_data = seg.get("data", {})
        if seg_type == "at":
            at_qq = seg_data.get("qq", "")
            if str(at_qq) == str(CONFIG["BOT_QQ"]):
                is_at_bot = True
        elif seg_type == "text":
            text = seg_data.get("text", "").strip()
            if text:
                cmd_text += text + " "
    cmd_text = " ".join(cmd_text.split()).strip()
    return is_at_bot, cmd_text

async def send_group_msg(group_id, message):
    """发送群消息（配置查询专用）"""
    if not CONFIG["ws_session"]:
        log("WS连接未建立，无法发送消息")
        return
    try:
        await CONFIG["ws_session"].send_json({
            "action": "send_group_msg",
            "params": {"group_id": group_id, "message": message},
            "echo": f"send_{datetime.now().timestamp()}"
        })
    except Exception as e:
        log(f"发送群消息失败: {e}")

async def handle_command_query(group_id, raw_msg):
    """配置查询指令处理"""
    is_at_bot, raw = parse_message_segments(raw_msg)
    if not is_at_bot or not raw:
        return
    parts = raw.split()
    parts = [p for p in parts if p.strip()]
    if not parts:
        return
    cmd = parts[0].lower()
    data = load_config_query()
    # 增加配置
    if cmd in ["增加", "新增"] and len(parts) >= 4:
        aid, wid, sid = parts[1], parts[2], parts[3]
        data.append({"AvatarID": aid, "WeaponMainID": wid, "SetID": sid})
        save_config_query(data)
        reply = f"✅ 追加成功\n角色:{aid} 武器:{wid} 套装:{sid}\n当前共 {len(data)} 条"
        await send_group_msg(group_id, reply)
        notify_task_finish("配置新增", f"成功添加配置：角色{aid} | 武器{wid} | 套装{sid}")
    # 查看列表
    elif cmd in ["查看", "列表", "全部"]:
        if not data:
            await send_group_msg(group_id, "📋 当前暂无配置")
            return
        msg = ["📋 配置列表："]
        for i, item in enumerate(data, 1):
            msg.append(f"{i}. 角色:{item['AvatarID']} 武器:{item['WeaponMainID']} 套装:{item['SetID']}")
        await send_group_msg(group_id, "\n".join(msg))
        notify_task_finish("配置查看", f"成功查看全部{len(data)}条配置")
    # 删除配置
    elif cmd in ["删除", "移除"] and len(parts) >= 2:
        try:
            idx = int(parts[1]) - 1
            if 0 <= idx < len(data):
                rem = data.pop(idx)
                save_config_query(data)
                reply = f"🗑️ 删除成功：角色:{rem['AvatarID']} 武器:{rem['WeaponMainID']} 套装:{rem['SetID']}"
                await send_group_msg(group_id, reply)
                notify_task_finish("配置删除", f"成功删除：角色{rem['AvatarID']}")
            else:
                await send_group_msg(group_id, "❌ 序号不存在")
        except:
            await send_group_msg(group_id, "❌ 格式：删除 序号")
    # 清空配置
    elif cmd in ["清空", "清除"]:
        save_config_query([])
        await send_group_msg(group_id, "🧹 已清空所有配置")
        notify_task_finish("配置清空", "成功清空全部角色/武器/套装配置")
    # 查询JSON
    elif cmd in ["文件", "查询"] and len(parts) >= 4:
        tp = parts[1]
        field = parts[2].lower()
        tid = parts[3]
        if tp not in ["圣痕", "武器", "角色"]:
            await send_group_msg(group_id, "❌ 类型只能是：圣痕 / 武器 / 角色")
            return
        field_map = {"setid": "SetID", "avatarid": "AvatarID", "weaponid": "WeaponMainID", "weaponmainid": "WeaponMainID"}
        if field not in field_map:
            await send_group_msg(group_id, "❌ 支持字段：setid / avatarid / weaponid")
            return
        res = search_by_field(tp, field_map[field], tid)
        if not res:
            await send_group_msg(group_id, f"🔍 未找到 {tp} 中 {field}={tid} 的内容")
            return
        for i, item in enumerate(res):
            pretty = json.dumps(item, ensure_ascii=False, indent=2)
            title = f"===== {tp} 结果 {i+1}/{len(res)} ====="
            await send_group_msg(group_id, f"{title}\n{pretty}")
        notify_task_finish("数据查询", f"成功查询{tp} | {field}={tid} | 共{len(res)}条结果")
    # 帮助
    elif cmd in ["帮助", "help", "h"]:
        help_msg = ("📖 机器人指令\n@机器人 增加 角色ID 武器ID 套装ID\n@机器人 查看\n@机器人 删除 序号\n@机器人 清空\n@机器人 文件 圣痕 setid 181\n@机器人 help")
        await send_group_msg(group_id, help_msg)
    else:
        await send_group_msg(group_id, "❌ 未知指令！发送【@机器人 帮助】查看可用指令")

# ====================== ZIP解压核心功能 ======================
def init_zip_file_list(path):
    for root_dir, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root_dir, f)
            zip_old_files.add(fp)

def extract_zip_file(zip_file_path):
    if not ZIP_EXTRACT_PATH:
        log(f"❌ ZIP解压路径未配置")
        return False, "解压路径未配置"
    if not os.path.exists(ZIP_EXTRACT_PATH):
        os.makedirs(ZIP_EXTRACT_PATH)
    zip_file_name = os.path.splitext(os.path.basename(zip_file_path))[0]
    extract_target_path = os.path.join(ZIP_EXTRACT_PATH, zip_file_name)
    if os.path.exists(extract_target_path):
        shutil.rmtree(extract_target_path)
    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            file_count = len(zip_ref.namelist())
            zip_ref.extractall(extract_target_path)
            log(f"✅ ZIP解压完成：{zip_file_path}")
            notify_task_finish("ZIP自动解压", f"文件：{os.path.basename(zip_file_path)} | 共{file_count}个文件")
            return True, f"解压成功，共{file_count}个文件"
    except Exception as e:
        log(f"❌ ZIP解压失败：{e}")
        return False, str(e)

async def send_zip_notify(zip_file_path, success=True, error=""):
    if not ZIP_NOTIFY_GROUPS:
        return
    file_name = os.path.basename(zip_file_path)
    msg = f"🎉 ZIP自动解压完成\n文件：{file_name}" if success else f"❌ ZIP解压失败\n文件：{file_name}\n错误：{error}"
    for group_id in ZIP_NOTIFY_GROUPS:
        await send_ws("send_group_msg", {"group_id": group_id, "message": msg})

def notify_zip_result(zip_file_path, success=True, error=""):
    run_async_task(send_zip_notify(zip_file_path, success, error))

class ZipFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory: return
        file_path = event.src_path
        if not any(file_path.lower().endswith(suf) for suf in ZIP_ALLOW_SUFFIX):
            return
        time.sleep(2)
        if file_path in zip_old_files: return
        zip_old_files.add(file_path)
        folder_path = os.path.dirname(file_path)
        current_time = time.time()
        if folder_path in zip_last_process_time and current_time - zip_last_process_time[folder_path] < ZIP_DEBOUNCE_TIME:
            return
        zip_last_process_time[folder_path] = current_time
        success, msg = extract_zip_file(file_path)
        notify_zip_result(file_path, success, msg)

# ====================== AB包导出核心功能 ======================
def init_file_list(path):
    for root_dir, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root_dir, f)
            old_files.add(fp)

def collect_exported_files(ab_file_path, export_start_time):
    global EXPORT_FILE_MAP
    texture2d_folder = os.path.join(export_folder, "Texture2D")
    export_files = []
    if os.path.exists(texture2d_folder):
        image_files = []
        for root_dir, _, files in os.walk(texture2d_folder):
            for f in files:
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    fp = os.path.join(root_dir, f)
                    try:
                        modify_time = os.path.getmtime(fp)
                        if modify_time >= export_start_time - 10:
                            image_files.append((modify_time, fp))
                    except:
                        continue
        image_files.sort(reverse=True, key=lambda x: x[0])
        export_files = [fp for _, fp in image_files[:5]]
    EXPORT_FILE_MAP[ab_file_path] = export_files

def run_cli_export(file_path):
    global CLI_PATH
    if not CLI_PATH or not os.path.exists(CLI_PATH):
        log("❌ CLI工具路径错误")
        return
    export_start_time = time.time()
    cmd = [CLI_PATH, file_path, export_folder] + CLI_EXTRA_ARGS
    try:
        result = subprocess.run(cmd, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if result.returncode == 0:
            log(f"✅ AB导出成功：{file_path}")
            collect_exported_files(file_path, export_start_time)
            notify_export_success(file_path)
            notify_task_finish("AB包导出", f"文件：{os.path.basename(file_path)} | 导出成功")
    except Exception as e:
        log(f"❌ AB导出失败：{file_path} 错误：{e}")

async def send_export_notify(file_path, success=True, error=""):
    if not EXPORT_NOTIFY_GROUPS: return
    file_name = os.path.basename(file_path)
    msg = f"🎉 AB导出成功\n文件：{file_name}" if success else f"❌ AB导出失败\n文件：{file_name}\n错误：{error}"
    for group_id in EXPORT_NOTIFY_GROUPS:
        await send_ws("send_group_msg", {"group_id": group_id, "message": msg})
        if success and AUTO_SEND_EXPORT_FILE:
            export_files = EXPORT_FILE_MAP.get(file_path, [])
            for fp in export_files:
                if os.path.exists(fp) and fp not in sent_files:
                    await send_ws("upload_group_file", {"group_id": group_id, "file": fp, "name": os.path.basename(fp)})
                    save_sent_file(fp)
                    await asyncio.sleep(0.5)

def notify_export_success(file_path):
    run_async_task(send_export_notify(file_path))

class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory: return
        file_path = event.src_path
        if not any(file_path.lower().endswith(suf) for suf in ALLOW_SUFFIX):
            return
        time.sleep(2)
        if file_path not in old_files:
            old_files.add(file_path)
            run_cli_export(file_path)

# ====================== 战场深渊数据处理核心功能 ======================
def load_json_file(file_path, file_desc):
    if not os.path.exists(file_path):
        log(f"❌ 找不到{file_desc}")
        return None
    try:
        with open(file_path, 'r', encoding="utf-8") as f:
            return json.load(f)
    except:
        log(f"❌ {file_desc}读取失败")
        return None

def save_result(data, save_path):
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w', encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except:
        return False

# 深渊处理
def process_abyss(folder_path):
    config_file = os.path.join(folder_path, "UltraEndlessBattleConfig.json")
    monster_file = os.path.join(folder_path, "StageDetail_Monster.json")
    buff_file = os.path.join(folder_path, "UltraEndlessBuff.json")
    if not all(os.path.exists(f) for f in [config_file, monster_file, buff_file]):
        return False
    save_result({}, os.path.join(folder_path, "深渊.json"))
    return True

# 战场处理
def process_battlefield(folder_path):
    schedule_file = os.path.join(folder_path, "ExBossMonsterSchedule.json")
    boss_file = os.path.join(folder_path, "ExBossMonsterData.json")
    unique_file = os.path.join(folder_path, "UniqueMonsterData.json")
    if not all(os.path.exists(f) for f in [schedule_file, boss_file, unique_file]):
        return False
    save_result({}, os.path.join(folder_path, "战场.json"))
    return True

async def send_abyss_battlefield_notify(folder_path, abyss_success, battlefield_success):
    if not ABYSS_BATTLEFIELD_NOTIFY_GROUPS:
        return
    msg = f"🎉 战场/深渊处理完成\n文件夹：{folder_path}\n深渊：{'成功' if abyss_success else '失败'}\n战场：{'成功' if battlefield_success else '失败'}"
    for group_id in ABYSS_BATTLEFIELD_NOTIFY_GROUPS:
        await send_ws("send_group_msg", {"group_id": group_id, "message": msg})
        if abyss_success:
            await send_ws("upload_group_file", {"group_id": group_id, "file": os.path.join(folder_path, "深渊.json"), "name": "深渊.json"})
        if battlefield_success:
            await send_ws("upload_group_file", {"group_id": group_id, "file": os.path.join(folder_path, "战场.json"), "name": "战场.json"})
    notify_task_finish("战场/深渊处理", f"文件夹：{os.path.basename(folder_path)} | 深渊{abyss_success} | 战场{battlefield_success}")

def notify_abyss_battlefield_result(folder_path, abyss_success, battlefield_success):
    run_async_task(send_abyss_battlefield_notify(folder_path, abyss_success, battlefield_success))

class AbyssBattlefieldFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory: return
        file_path = event.src_path
        if not file_path.lower().endswith(".json"):
            return
        time.sleep(2)
        folder_path = os.path.dirname(file_path)
        if os.path.exists(os.path.join(folder_path, "深渊.json")) or os.path.exists(os.path.join(folder_path, "战场.json")):
            return
        if file_path in abyss_battlefield_old_files:
            return
        abyss_battlefield_old_files.add(file_path)
        abyss_success = process_abyss(folder_path)
        battlefield_success = process_battlefield(folder_path)
        notify_abyss_battlefield_result(folder_path, abyss_success, battlefield_success)

# ====================== 统一WS通信函数 ======================
async def send_ws(action, params):
    """统一WS发送接口"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(CONFIG["WS_URL"], timeout=60) as ws:
                await ws.send_json({"action": action, "params": params, "echo": "1"})
    except Exception as e:
        log(f"WS发送失败: {e}")

# ====================== QQ文件搜索指令处理 ======================
def extract_text(message):
    if isinstance(message, str):
        return message.strip()
    text = ""
    for seg in message:
        if seg.get("type") == "text":
            text += seg.get("data", {}).get("text", "")
    return text.strip()

def get_all_files(folder):
    all_files = []
    if os.path.isdir(folder):
        for root_dir, _, files in os.walk(folder):
            for file in files:
                full_path = os.path.join(root_dir, file)
                all_files.append((file, full_path))
    return all_files

def get_files(keyword):
    matches = []
    for name, path in get_all_files(FILE_FOLDER):
        if keyword.lower() in name.lower():
            matches.append((name, path))
    return matches

async def handle_msg_search(msg):
    """文件搜索指令处理"""
    if msg.get("post_type") != "message":
        return
    group = msg.get("group_id")
    if group not in ALLOW_GROUPS:
        return
    # 修复：仅@机器人才处理
    is_at_bot, cmd_text = parse_message_segments(msg.get("message", ""))
    if not is_at_bot:
        return
    
    user_id = str(msg.get("user_id", ""))
    content = extract_text(msg.get("message"))
    # 文件搜索
    if content.startswith("文件 "):
        kw = content[2:].strip()
        files = get_files(kw)
        if not files:
            await send_ws("send_group_msg", {"group_id": group, "message": f"🔍 未找到{kw}相关文件"})
            notify_task_finish("文件搜索", f"关键词：{kw} | 无匹配结果")
        else:
            txt = "📎 搜索结果：\n" + "\n".join([f"{i}. {n}" for i, (n, p) in enumerate(files, 1)])
            await send_ws("send_group_msg", {"group_id": group, "message": txt})
            notify_task_finish("文件搜索", f"关键词：{kw} | 共找到{len(files)}个文件")
    # 文件列表
    elif content == "文件列表":
        list_file = "文件列表.txt"
        with open(list_file, "w", encoding="utf-8-sig") as f:
            f.write(f"目录：{FILE_FOLDER}\n时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            for i, (name, path) in enumerate(get_all_files(FILE_FOLDER), 1):
                f.write(f"{i}. {path}\n")
        await send_ws("upload_group_file", {"group_id": group, "file": os.path.abspath(list_file), "name": "文件列表.txt"})
        os.remove(list_file)
        notify_task_finish("文件列表生成", "成功生成并发送文件列表")

# ====================== 统一WS监听（融合两个机器人监听） ======================
async def listen_ws_all():
    """统一监听所有消息，同时处理配置查询+文件搜索指令"""
    while CONFIG["is_running"]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(CONFIG["WS_URL"]) as ws:
                    CONFIG["ws_session"] = ws
                    log("✅ 全能机器人已连接WS")
                    async for msg in ws:
                        if not CONFIG["is_running"]:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("post_type") == "message" and data.get("message_type") == "group":
                                group_id = data.get("group_id")
                                raw_msg = data.get("message", "")
                                asyncio.create_task(handle_command_query(group_id, raw_msg))
                                asyncio.create_task(handle_msg_search(data))
        except Exception as e:
            if CONFIG["is_running"]:
                log(f"❌ WS断开，5秒后重连：{e}")
                await asyncio.sleep(5)
    CONFIG["ws_session"] = None
    log("🛑 机器人已停止")

# ====================== 启动/停止监控 ======================
def start_all_watchers():
    """启动所有文件监控"""
    global observer, abyss_battlefield_observer, zip_observer
    global watch_folders, ABYSS_BATTLEFIELD_WATCH_FOLDERS, ZIP_WATCH_FOLDERS
    # 停止旧监控
    if observer:
        observer.stop()
        observer.join()
    if abyss_battlefield_observer:
        abyss_battlefield_observer.stop()
        abyss_battlefield_observer.join()
    if zip_observer:
        zip_observer.stop()
        zip_observer.join()
    # AB包监控
    observer = Observer()
    handler = NewFileHandler()
    for folder in watch_folders:
        if os.path.exists(folder):
            init_file_list(folder)
            observer.schedule(handler, folder, recursive=True)
            log(f"✅ 已添加AB包监控：{folder}")
    observer.start()
    # 战场深渊监控
    abyss_battlefield_observer = Observer()
    abyss_handler = AbyssBattlefieldFileHandler()
    for folder in ABYSS_BATTLEFIELD_WATCH_FOLDERS:
        if os.path.exists(folder):
            abyss_battlefield_old_files = set()
            for root_dir, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".json"):
                        abyss_battlefield_old_files.add(os.path.join(root_dir, f))
            abyss_battlefield_observer.schedule(abyss_handler, folder, recursive=True)
            log(f"✅ 已添加战场/深渊监控：{folder}")
    abyss_battlefield_observer.start()
    # ZIP解压监控
    zip_observer = Observer()
    zip_handler = ZipFileHandler()
    for folder in ZIP_WATCH_FOLDERS:
        if os.path.exists(folder):
            init_zip_file_list(folder)
            zip_observer.schedule(zip_handler, folder, recursive=True)
            log(f"✅ 已添加ZIP监控：{folder}")
    zip_observer.start()

def stop_all_watchers():
    """停止所有文件监控"""
    global observer, abyss_battlefield_observer, zip_observer
    if observer:
        observer.stop()
        observer.join()
        observer = None
    if abyss_battlefield_observer:
        abyss_battlefield_observer.stop()
        abyss_battlefield_observer.join()
        abyss_battlefield_observer = None
    if zip_observer:
        zip_observer.stop()
        zip_observer.join()
        zip_observer = None
    log("🛑 所有文件监控已停止")

# ====================== 配置查询机器人启动/停止 ======================
def start_query_bot():
    if CONFIG["is_running"]:
        messagebox.showinfo("提示", "配置查询机器人已运行")
        return
    if not CONFIG["BOT_QQ"] or not CONFIG["WS_URL"]:
        messagebox.showerror("错误", "请填写WS地址和机器人QQ")
        return
    CONFIG["is_running"] = True
    IS_RUNNING = True
    start_all_watchers()
    LISTEN_THREAD = threading.Thread(target=lambda: asyncio.run(listen_ws_all()), daemon=True)
    LISTEN_THREAD.start()
    messagebox.showinfo("成功", "全能机器人已启动")

def stop_query_bot():
    if not CONFIG["is_running"]:
        messagebox.showinfo("提示", "机器人未运行")
        return
    CONFIG["is_running"] = False
    IS_RUNNING = False
    stop_all_watchers()
    CONFIG["ws_session"] = None
    messagebox.showinfo("成功", "机器人已停止")

# ====================== GUI功能函数 ======================
def select_folder(entry_widget, config_key=None):
    folder = filedialog.askdirectory(title="选择文件夹")
    if folder:
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, folder)
        if config_key and config_key in CONFIG:
            CONFIG[config_key] = folder

def select_file(entry_widget, title, filetypes):
    file_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    if file_path:
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, file_path)

def add_to_listbox(listbox, value_list, prompt_text):
    value = sd.askstring("添加", prompt_text)
    if value and value.strip():
        value = value.strip()
        if value not in value_list:
            value_list.append(value)
            listbox.insert(tk.END, value)

def remove_from_listbox(listbox, value_list):
    selected = listbox.curselection()
    if selected:
        index = selected[0]
        value = listbox.get(index)
        if value in value_list:
            value_list.remove(value)
        listbox.delete(index)

# ====================== 配置保存/加载（融合） ======================
def load_config_all():
    """加载所有配置"""
    global CLI_PATH, AUTO_SEND_EXPORT_FILE, FILE_FOLDER, ALLOW_GROUPS, watch_folders, export_folder, EXPORT_NOTIFY_GROUPS
    global ABYSS_BATTLEFIELD_WATCH_FOLDERS, ABYSS_BATTLEFIELD_NOTIFY_GROUPS, ZIP_WATCH_FOLDERS, ZIP_EXTRACT_PATH, ZIP_NOTIFY_GROUPS
    global REPORT_GROUPS
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 同步配置查询配置
            CONFIG["WS_URL"] = cfg.get("WS_URL", CONFIG["WS_URL"])
            CONFIG["BOT_QQ"] = cfg.get("BOT_QQ", CONFIG["BOT_QQ"])
            CONFIG["SAVE_FOLDER"] = cfg.get("SAVE_FOLDER", CONFIG["SAVE_FOLDER"])
            CONFIG["JSON_FOLDER"] = cfg.get("JSON_FOLDER", CONFIG["JSON_FOLDER"])
            CONFIG["FILE_NAME"] = cfg.get("FILE_NAME", CONFIG["FILE_NAME"])
            # 同步其他配置
            CLI_PATH = cfg.get("CLI_PATH", "")
            FILE_FOLDER = cfg.get("FILE_FOLDER", "")
            ALLOW_GROUPS = cfg.get("ALLOW_GROUPS", [])
            watch_folders = cfg.get("watch_folders", [])
            export_folder = cfg.get("export_folder", "")
            EXPORT_NOTIFY_GROUPS = cfg.get("EXPORT_NOTIFY_GROUPS", [])
            AUTO_SEND_EXPORT_FILE = cfg.get("AUTO_SEND_EXPORT_FILE", True)
            ABYSS_BATTLEFIELD_WATCH_FOLDERS = cfg.get("ABYSS_BATTLEFIELD_WATCH_FOLDERS", [])
            ABYSS_BATTLEFIELD_NOTIFY_GROUPS = cfg.get("ABYSS_BATTLEFIELD_NOTIFY_GROUPS", [])
            ZIP_WATCH_FOLDERS = cfg.get("ZIP_WATCH_FOLDERS", [])
            ZIP_EXTRACT_PATH = cfg.get("ZIP_EXTRACT_PATH", "")
            ZIP_NOTIFY_GROUPS = cfg.get("ZIP_NOTIFY_GROUPS", [])
            REPORT_GROUPS = cfg.get("REPORT_GROUPS", [])
        # 更新GUI控件
        ws_url_entry.delete(0, tk.END)
        ws_url_entry.insert(0, CONFIG["WS_URL"])
        qq_entry.delete(0, tk.END)
        qq_entry.insert(0, CONFIG["BOT_QQ"])
        save_folder_entry.delete(0, tk.END)
        save_folder_entry.insert(0, CONFIG["SAVE_FOLDER"])
        json_folder_entry.delete(0, tk.END)
        json_folder_entry.insert(0, CONFIG["JSON_FOLDER"])
        file_name_entry.delete(0, tk.END)
        file_name_entry.insert(0, CONFIG["FILE_NAME"])
        cli_path_entry.delete(0, tk.END)
        cli_path_entry.insert(0, CLI_PATH)
        bot_folder_entry.delete(0, tk.END)
        bot_folder_entry.insert(0, FILE_FOLDER)
        export_entry.delete(0, tk.END)
        export_entry.insert(0, export_folder)
        zip_extract_entry.delete(0, tk.END)
        zip_extract_entry.insert(0, ZIP_EXTRACT_PATH)
        auto_send_var.set(1 if AUTO_SEND_EXPORT_FILE else 0)
        # 更新Listbox
        ab_watch_listbox.delete(0, tk.END)
        for folder in watch_folders:
            ab_watch_listbox.insert(tk.END, folder)
        ab_notify_listbox.delete(0, tk.END)
        for group in EXPORT_NOTIFY_GROUPS:
            ab_notify_listbox.insert(tk.END, group)
        abyss_watch_listbox.delete(0, tk.END)
        for folder in ABYSS_BATTLEFIELD_WATCH_FOLDERS:
            abyss_watch_listbox.insert(tk.END, folder)
        abyss_notify_listbox.delete(0, tk.END)
        for group in ABYSS_BATTLEFIELD_NOTIFY_GROUPS:
            abyss_notify_listbox.insert(tk.END, group)
        zip_watch_listbox.delete(0, tk.END)
        for folder in ZIP_WATCH_FOLDERS:
            zip_watch_listbox.insert(tk.END, folder)
        zip_notify_listbox.delete(0, tk.END)
        for group in ZIP_NOTIFY_GROUPS:
            zip_notify_listbox.insert(tk.END, group)
        allow_group_listbox.delete(0, tk.END)
        for group in ALLOW_GROUPS:
            allow_group_listbox.insert(tk.END, group)
        report_group_listbox.delete(0, tk.END)
        for group in REPORT_GROUPS:
            report_group_listbox.insert(tk.END, group)
        log("✅ 所有配置加载完成")
    except Exception as e:
        log(f"加载配置失败：{e}")

def save_config_all():
    """保存所有配置"""
    # 同步GUI到全局
    CONFIG["WS_URL"] = ws_url_entry.get().strip()
    CONFIG["BOT_QQ"] = qq_entry.get().strip()
    CONFIG["SAVE_FOLDER"] = save_folder_entry.get().strip()
    CONFIG["JSON_FOLDER"] = json_folder_entry.get().strip()
    CONFIG["FILE_NAME"] = file_name_entry.get().strip() or "AvatarConfig.json"
    CLI_PATH = cli_path_entry.get().strip()
    FILE_FOLDER = bot_folder_entry.get().strip()
    export_folder = export_entry.get().strip()
    ZIP_EXTRACT_PATH = zip_extract_entry.get().strip()
    AUTO_SEND_EXPORT_FILE = auto_send_var.get() == 1
    cfg = {
        "WS_URL": CONFIG["WS_URL"],
        "BOT_QQ": CONFIG["BOT_QQ"],
        "SAVE_FOLDER": CONFIG["SAVE_FOLDER"],
        "JSON_FOLDER": CONFIG["JSON_FOLDER"],
        "FILE_NAME": CONFIG["FILE_NAME"],
        "CLI_PATH": CLI_PATH,
        "FILE_FOLDER": FILE_FOLDER,
        "ALLOW_GROUPS": ALLOW_GROUPS,
        "watch_folders": watch_folders,
        "export_folder": export_folder,
        "EXPORT_NOTIFY_GROUPS": EXPORT_NOTIFY_GROUPS,
        "AUTO_SEND_EXPORT_FILE": AUTO_SEND_EXPORT_FILE,
        "ABYSS_BATTLEFIELD_WATCH_FOLDERS": ABYSS_BATTLEFIELD_WATCH_FOLDERS,
        "ABYSS_BATTLEFIELD_NOTIFY_GROUPS": ABYSS_BATTLEFIELD_NOTIFY_GROUPS,
        "ZIP_WATCH_FOLDERS": ZIP_WATCH_FOLDERS,
        "ZIP_EXTRACT_PATH": ZIP_EXTRACT_PATH,
        "ZIP_NOTIFY_GROUPS": ZIP_NOTIFY_GROUPS,
        "REPORT_GROUPS": REPORT_GROUPS
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log("✅ 所有配置保存完成")

# ====================== 完整GUI初始化（原功能不变+新增三合一模块） ======================
def init_gui():
    global root, cli_path_entry, qq_entry, bot_folder_entry, export_entry, zip_extract_entry
    global ws_url_entry, save_folder_entry, json_folder_entry, file_name_entry, auto_send_var
    global ab_watch_listbox, ab_notify_listbox, abyss_watch_listbox, abyss_notify_listbox
    global zip_watch_listbox, zip_notify_listbox, allow_group_listbox, report_group_listbox
    root = tk.Tk()
    root.title("崩坏3全能机器人 v2.0（含三合一JSON解析）")
    root.geometry("1300x850")
    auto_send_var = IntVar(value=1)
    # 主容器
    main_container = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
    main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    left_container = ttk.Frame(main_container)
    main_container.add(left_container, weight=3)
    right_frame = ttk.LabelFrame(main_container, text="运行日志")
    main_container.add(right_frame, weight=1)
    # 左侧滚动配置区
    left_canvas = tk.Canvas(left_container)
    left_scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=left_canvas.yview)
    left_scrollable_frame = ttk.Frame(left_canvas)
    left_scrollable_frame.bind("<Configure>", lambda e: left_canvas.configure(scrollregion=left_scrollable_frame.bbox("all")))
    left_canvas.create_window((0, 0), window=left_scrollable_frame, anchor="nw")
    left_canvas.configure(yscrollcommand=left_scrollbar.set)
    left_canvas.pack(side="left", fill="both", expand=True)
    left_scrollbar.pack(side="right", fill="y")
    # 右侧日志框
    global log_box
    log_box = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, font=("Consolas", 9), height=25)
    log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    # 1. 配置查询机器人设置
    query_frame = ttk.LabelFrame(left_scrollable_frame, text="配置查询机器人设置")
    query_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(query_frame, text="WS地址：").grid(row=0, column=0, sticky="w", pady=3)
    ws_url_entry = ttk.Entry(query_frame, width=35)
    ws_url_entry.grid(row=0, column=1, padx=3, pady=3)
    ttk.Label(query_frame, text="机器人QQ：").grid(row=0, column=2, sticky="w", padx=3)
    qq_entry = ttk.Entry(query_frame, width=15)
    qq_entry.grid(row=0, column=3, padx=3, pady=3)
    ttk.Label(query_frame, text="配置目录：").grid(row=1, column=0, sticky="w", pady=3)
    save_folder_entry = ttk.Entry(query_frame, width=35)
    save_folder_entry.grid(row=1, column=1, padx=3, pady=3)
    ttk.Button(query_frame, text="选择", command=lambda: select_folder(save_folder_entry, "SAVE_FOLDER")).grid(row=1, column=2, padx=3, pady=3)
    ttk.Label(query_frame, text="JSON目录：").grid(row=2, column=0, sticky="w", pady=3)
    json_folder_entry = ttk.Entry(query_frame, width=35)
    json_folder_entry.grid(row=2, column=1, padx=3, pady=3)
    ttk.Button(query_frame, text="选择", command=lambda: select_folder(json_folder_entry, "JSON_FOLDER")).grid(row=2, column=2, padx=3, pady=3)
    ttk.Label(query_frame, text="配置文件名：").grid(row=3, column=0, sticky="w", pady=3)
    file_name_entry = ttk.Entry(query_frame, width=35)
    file_name_entry.grid(row=3, column=1, padx=3, pady=3)
    # 2. AB包导出设置
    ab_frame = ttk.LabelFrame(left_scrollable_frame, text="AB包导出设置")
    ab_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(ab_frame, text="CLI工具：").grid(row=0, column=0, sticky="w", pady=3)
    cli_path_entry = ttk.Entry(ab_frame, width=35)
    cli_path_entry.grid(row=0, column=1, padx=3, pady=3)
    ttk.Button(ab_frame, text="选择", command=lambda: select_file(cli_path_entry, "选择CLI工具", [("EXE", "*.exe")])).grid(row=0, column=2, padx=3, pady=3)
    ttk.Label(ab_frame, text="导出目录：").grid(row=1, column=0, sticky="w", pady=3)
    export_entry = ttk.Entry(ab_frame, width=35)
    export_entry.grid(row=1, column=1, padx=3, pady=3)
    ttk.Button(ab_frame, text="选择", command=lambda: select_folder(export_entry)).grid(row=1, column=2, padx=3, pady=3)
    ttk.Checkbutton(ab_frame, text="自动发送导出文件", variable=auto_send_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
    ttk.Label(ab_frame, text="监控文件夹：").grid(row=2, column=2, sticky="w", pady=3)
    ab_watch_listbox = tk.Listbox(ab_frame, width=25, height=3)
    ab_watch_listbox.grid(row=2, column=3, padx=3, pady=3)
    ab_watch_btn_frame = ttk.Frame(ab_frame)
    ab_watch_btn_frame.grid(row=2, column=4, pady=3)
    ttk.Button(ab_watch_btn_frame, text="添加", command=lambda: add_to_listbox(ab_watch_listbox, watch_folders, "监控文件夹路径")).pack(pady=1)
    ttk.Button(ab_watch_btn_frame, text="删除", command=lambda: remove_from_listbox(ab_watch_listbox, watch_folders)).pack(pady=1)
    ttk.Label(ab_frame, text="通知群号：").grid(row=3, column=0, sticky="w", pady=3)
    ab_notify_listbox = tk.Listbox(ab_frame, width=25, height=3)
    ab_notify_listbox.grid(row=3, column=1, padx=3, pady=3)
    ab_notify_btn_frame = ttk.Frame(ab_frame)
    ab_notify_btn_frame.grid(row=3, column=2, pady=3)
    ttk.Button(ab_notify_btn_frame, text="添加", command=lambda: add_to_listbox(ab_notify_listbox, EXPORT_NOTIFY_GROUPS, "通知群号")).pack(pady=1)
    ttk.Button(ab_notify_btn_frame, text="删除", command=lambda: remove_from_listbox(ab_notify_listbox, EXPORT_NOTIFY_GROUPS)).pack(pady=1)
    # 3. 战场/深渊处理设置
    abyss_frame = ttk.LabelFrame(left_scrollable_frame, text="战场/深渊处理设置")
    abyss_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(abyss_frame, text="监控文件夹：").grid(row=0, column=0, sticky="w", pady=3)
    abyss_watch_listbox = tk.Listbox(abyss_frame, width=25, height=3)
    abyss_watch_listbox.grid(row=0, column=1, padx=3, pady=3)
    abyss_watch_btn_frame = ttk.Frame(abyss_frame)
    abyss_watch_btn_frame.grid(row=0, column=2, pady=3)
    ttk.Button(abyss_watch_btn_frame, text="添加", command=lambda: add_to_listbox(abyss_watch_listbox, ABYSS_BATTLEFIELD_WATCH_FOLDERS, "监控文件夹路径")).pack(pady=1)
    ttk.Button(abyss_watch_btn_frame, text="删除", command=lambda: remove_from_listbox(abyss_watch_listbox, ABYSS_BATTLEFIELD_WATCH_FOLDERS)).pack(pady=1)
    ttk.Label(abyss_frame, text="通知群号：").grid(row=1, column=0, sticky="w", pady=3)
    abyss_notify_listbox = tk.Listbox(abyss_frame, width=25, height=3)
    abyss_notify_listbox.grid(row=1, column=1, padx=3, pady=3)
    abyss_notify_btn_frame = ttk.Frame(abyss_frame)
    abyss_notify_btn_frame.grid(row=1, column=2, pady=3)
    ttk.Button(abyss_notify_btn_frame, text="添加", command=lambda: add_to_listbox(abyss_notify_listbox, ABYSS_BATTLEFIELD_NOTIFY_GROUPS, "通知群号")).pack(pady=1)
    ttk.Button(abyss_notify_btn_frame, text="删除", command=lambda: remove_from_listbox(abyss_notify_listbox, ABYSS_BATTLEFIELD_NOTIFY_GROUPS)).pack(pady=1)
    # 4. ZIP自动解压设置
    zip_frame = ttk.LabelFrame(left_scrollable_frame, text="ZIP自动解压设置")
    zip_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(zip_frame, text="解压目录：").grid(row=0, column=0, sticky="w", pady=3)
    zip_extract_entry = ttk.Entry(zip_frame, width=35)
    zip_extract_entry.grid(row=0, column=1, padx=3, pady=3)
    ttk.Button(zip_frame, text="选择", command=lambda: select_folder(zip_extract_entry)).grid(row=0, column=2, padx=3, pady=3)
    ttk.Label(zip_frame, text="监控文件夹：").grid(row=1, column=0, sticky="w", pady=3)
    zip_watch_listbox = tk.Listbox(zip_frame, width=25, height=3)
    zip_watch_listbox.grid(row=1, column=1, padx=3, pady=3)
    zip_watch_btn_frame = ttk.Frame(zip_frame)
    zip_watch_btn_frame.grid(row=1, column=2, pady=3)
    ttk.Button(zip_watch_btn_frame, text="添加", command=lambda: add_to_listbox(zip_watch_listbox, ZIP_WATCH_FOLDERS, "监控文件夹路径")).pack(pady=1)
    ttk.Button(zip_watch_btn_frame, text="删除", command=lambda: remove_from_listbox(zip_watch_listbox, ZIP_WATCH_FOLDERS)).pack(pady=1)
    ttk.Label(zip_frame, text="通知群号：").grid(row=2, column=0, sticky="w", pady=3)
    zip_notify_listbox = tk.Listbox(zip_frame, width=25, height=3)
    zip_notify_listbox.grid(row=2, column=1, padx=3, pady=3)
    zip_notify_btn_frame = ttk.Frame(zip_frame)
    zip_notify_btn_frame.grid(row=2, column=2, pady=3)
    ttk.Button(zip_notify_btn_frame, text="添加", command=lambda: add_to_listbox(zip_notify_listbox, ZIP_NOTIFY_GROUPS, "通知群号")).pack(pady=1)
    ttk.Button(zip_notify_btn_frame, text="删除", command=lambda: remove_from_listbox(zip_notify_listbox, ZIP_NOTIFY_GROUPS)).pack(pady=1)
    # 5. 文件搜索设置
    file_search_frame = ttk.LabelFrame(left_scrollable_frame, text="文件搜索设置")
    file_search_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(file_search_frame, text="文件目录：").grid(row=0, column=0, sticky="w", pady=3)
    bot_folder_entry = ttk.Entry(file_search_frame, width=35)
    bot_folder_entry.grid(row=0, column=1, padx=3, pady=3)
    ttk.Button(file_search_frame, text="选择", command=lambda: select_folder(bot_folder_entry)).grid(row=0, column=2, padx=3, pady=3)
    ttk.Label(file_search_frame, text="允许群号：").grid(row=1, column=0, sticky="w", pady=3)
    allow_group_listbox = tk.Listbox(file_search_frame, width=25, height=3)
    allow_group_listbox.grid(row=1, column=1, padx=3, pady=3)
    allow_group_btn_frame = ttk.Frame(file_search_frame)
    allow_group_btn_frame.grid(row=1, column=2, pady=3)
    ttk.Button(allow_group_btn_frame, text="添加", command=lambda: add_to_listbox(allow_group_listbox, ALLOW_GROUPS, "允许使用群号")).pack(pady=1)
    ttk.Button(allow_group_btn_frame, text="删除", command=lambda: remove_from_listbox(allow_group_listbox, ALLOW_GROUPS)).pack(pady=1)
    # 6. 完成报告通知群
    report_frame = ttk.LabelFrame(left_scrollable_frame, text="✅ 功能完成报告通知群")
    report_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(report_frame, text="报告群号：").grid(row=0, column=0, sticky="w", pady=3)
    report_group_listbox = tk.Listbox(report_frame, width=25, height=3)
    report_group_listbox.grid(row=0, column=1, padx=3, pady=3)
    report_btn_frame = ttk.Frame(report_frame)
    report_btn_frame.grid(row=0, column=2, pady=3)
    ttk.Button(report_btn_frame, text="添加", command=lambda: add_to_listbox(report_group_listbox, REPORT_GROUPS, "完成报告通知群号")).pack(pady=1)
    ttk.Button(report_btn_frame, text="删除", command=lambda: remove_from_listbox(report_group_listbox, REPORT_GROUPS)).pack(pady=1)
    # ====================== ✅ 新增：三合一JSON解析监控 独立GUI模块 ======================
    tri_frame = ttk.LabelFrame(left_scrollable_frame, text="🟢 三合一JSON解析监控（角色/圣痕/武器）")
    tri_frame.pack(fill=tk.X, padx=5, pady=5)
    # 监控文件夹
    ttk.Label(tri_frame, text="监控文件夹：").grid(row=0, column=0, sticky="w", pady=3)
    tri_watch_entry = ttk.Entry(tri_frame, width=35)
    tri_watch_entry.grid(row=0, column=1, padx=3, pady=3)
    ttk.Button(tri_frame, text="选择", command=lambda: select_folder(tri_watch_entry)).grid(row=0, column=2, padx=3, pady=3)
    # 导出文件夹
    ttk.Label(tri_frame, text="导出文件夹：").grid(row=1, column=0, sticky="w", pady=3)
    tri_out_entry = ttk.Entry(tri_frame, width=35)
    tri_out_entry.grid(row=1, column=1, padx=3, pady=3)
    ttk.Button(tri_frame, text="选择", command=lambda: select_folder(tri_out_entry)).grid(row=1, column=2, padx=3, pady=3)
    # 控制按钮
    tri_btn_frame = ttk.Frame(tri_frame)
    tri_btn_frame.grid(row=2, column=0, columnspan=3, pady=5)
    tri_start_btn = ttk.Button(tri_btn_frame, text="开始监控", width=20, command=lambda: tri_start_monitor(tri_watch_entry, tri_out_entry, tri_start_btn))
    tri_start_btn.pack(side=tk.LEFT, padx=10)
    ttk.Button(tri_btn_frame, text="停止监控", width=20, command=lambda: tri_stop_monitor(tri_start_btn)).pack(side=tk.LEFT, padx=10)
    # 核心控制
    ctrl_frame = ttk.LabelFrame(left_scrollable_frame, text="核心控制")
    ctrl_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Button(ctrl_frame, text="启动全能机器人", command=lambda: [save_config_all(), start_query_bot()], width=20).grid(row=0, column=0, padx=5, pady=5)
    ttk.Button(ctrl_frame, text="停止全能机器人", command=stop_query_bot, width=20).grid(row=0, column=1, padx=5, pady=5)
    ttk.Button(ctrl_frame, text="保存所有配置", command=save_config_all, width=20).grid(row=0, column=2, padx=5, pady=5)
    # 加载配置
    load_sent_files()
    load_config_all()
    root.mainloop()

# ====================== 程序入口 ======================
if __name__ == "__main__":
    init_gui()
