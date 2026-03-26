#!/usr/bin/env python3
"""
Bangumi 数据导入脚本
用于从 Bangumi dump 提取角色和作品别名

用法:
    python import_bangumi.py <dump_dir> [output_file]

示例:
    python import_bangumi.py ./dump-2026-03-10 ./aliases.json
"""

import argparse
import json
import logging
import os
import sys
import zipfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def find_dump_files(dump_dir: str) -> dict:
    """查找 dump 目录中的文件"""
    dump_path = Path(dump_dir)
    files = {}
    
    if dump_path.is_file():
        name = dump_path.name.lower()
        if name == "character.jsonlines" or name == "character.jsonl" or name == "character.json":
            files["character"] = str(dump_path.absolute())
        elif name == "subject-characters.jsonlines":
            files["subject_characters"] = str(dump_path.absolute())
        elif name.startswith("subject.") and ("jsonlines" in name or "jsonl" in name or name.endswith(".json")):
            files["subject"] = str(dump_path.absolute())
        return files
    
    for f in dump_path.glob("character.jsonlines"):
        files["character"] = str(f)
    for f in dump_path.glob("subject-characters.jsonlines"):
        files["subject_characters"] = str(f)
    for f in dump_path.glob("subject.jsonlines"):
        files["subject"] = str(f)
    
    if not files.get("character"):
        for f in dump_path.glob("character.json"):
            if "character" not in files:
                files["character"] = str(f)
    
    if not files.get("subject_characters"):
        for f in dump_path.glob("subject-characters.json"):
            if "subject_characters" not in files:
                files["subject_characters"] = str(f)
    
    if not files.get("subject"):
        for f in dump_path.glob("subject.json"):
            if "subject" not in files:
                files["subject"] = str(f)
    
    if not files:
        for f in dump_path.glob("*.zip"):
            files["zip"] = str(f)
        for f in dump_path.glob("*.7z"):
            files["7z"] = str(f)
    
    return files


def load_jsonlines(file_path: str) -> list:
    """加载 JSONL (JSON Lines) 文件"""
    data = []
    if not os.path.exists(file_path):
        return data
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON 解析错误 (文件: {file_path}, 行: {line_num}): {e}")
    return data


def load_json_from_zip(zip_path: str, filename: str) -> list:
    """从 zip 文件中加载 JSONL"""
    result = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            if filename.lower() in name.lower():
                with z.open(name) as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if line:
                            try:
                                result.append(json.loads(line))
                            except json.JSONDecodeError as e:
                                logger.warning(f"JSON 解析错误 (ZIP: {zip_path}, 文件: {name}, 行: {line_num}): {e}")
    return result


def extract_character_aliases(characters: list) -> dict:
    """提取角色别名"""
    import re
    aliases = {}
    
    for char in characters:
        name = char.get("name", "").strip()
        if not name:
            continue
        
        alias_list = []
        
        infobox = char.get("infobox", "") or ""
        if infobox:
            cn_match = re.search(r'简体中文名=\s*([^|\n]+)', infobox)
            if cn_match:
                cn_name = cn_match.group(1).strip()
                if cn_name and cn_name != name and not cn_name.startswith('http'):
                    alias_list.append(cn_name)
            
            cn2_match = re.search(r'第二中文名=\s*([^|\n]+)', infobox)
            if cn2_match:
                cn2_name = cn2_match.group(1).strip()
                if cn2_name and cn2_name != name and not cn2_name.startswith('http'):
                    alias_list.append(cn2_name)
            
            alias_block = re.search(r'别名=\{(.+?)\}\}', infobox, re.DOTALL)
            if alias_block:
                alias_text = alias_block.group(1)
                alias_items = re.findall(r'\[([^\]]+)\]', alias_text)
                for alias_item in alias_items:
                    if '|' in alias_item:
                        alias_item = alias_item.split('|', 1)[1].strip()
                    else:
                        alias_item = alias_item.strip()
                    if alias_item and alias_item != name and not alias_item.startswith('http'):
                        alias_list.append(alias_item)
        
        alias_list = list(set(alias_list))
        
        if alias_list:
            aliases[name] = alias_list
    
    return aliases


def extract_work_aliases(subjects: list) -> dict:
    """提取作品别名"""
    aliases = {}
    
    for subject in subjects:
        name = subject.get("name", "").strip()
        if not name:
            continue
        
        alias_list = []
        
        name_cn = subject.get("name_cn", "").strip()
        if name_cn and name_cn != name:
            alias_list.append(name_cn)
        
        alias_list = list(set(alias_list))
        
        if alias_list:
            aliases[name] = alias_list
    
    return aliases


def main():
    parser = argparse.ArgumentParser(
        description="从 Bangumi dump 提取角色和作品别名",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持的文件格式:
  - .jsonlines (JSON Lines)
  - .jsonl (JSON Lines)
  - .json (JSON Array)
  - .zip (包含上述文件)

需要以下文件:
  - subject.jsonlines (作品数据)
  - subject-characters.jsonlines (作品角色关联)
  - character.jsonlines (角色数据)

示例:
  python import_bangumi.py ./dump-2026-03-10
  python import_bangumi.py ./dump-2026-03-10 ./my_aliases.json
        """
    )
    parser.add_argument("dump_dir", help="Bangumi dump 目录或文件路径")
    parser.add_argument("output_file", nargs="?", default="aliases.json", help="输出文件路径 (默认: aliases.json)")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细日志")
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    dump_dir = args.dump_dir
    output_file = args.output_file
    
    logger.info(f"正在扫描: {dump_dir}")
    
    dump_path = Path(dump_dir)
    if dump_path.is_dir():
        logger.info("目录中的文件:")
        for f in sorted(dump_path.iterdir()):
            if f.is_file():
                logger.info(f"  - {f.name}")
    
    files = find_dump_files(dump_dir)
    if not files:
        logger.error("未找到 dump 文件!")
        sys.exit(1)
    
    logger.info(f"找到文件: {files}")
    
    result = {
        "description": "角色和作品别名库 - 从 Bangumi 数据导入",
        "version": "1.0.0",
        "character": {},
        "work": {}
    }
    
    valid_character_ids = set()
    valid_subject_ids = set()
    
    # 1. 加载 subject.jsonlines，筛选 type=2 (动画) 和 type=4 (游戏)
    if "subject" in files:
        logger.info(f"加载作品数据: {files['subject']}")
        subjects = load_jsonlines(files["subject"])
        logger.info(f"共 {len(subjects)} 条作品数据")
        
        # 筛选 type=2 和 type=4
        filtered_subjects = [s for s in subjects if s.get("type") in [2, 4]]
        logger.info(f"筛选 type=2(动画) 和 type=4(游戏): {len(filtered_subjects)} 条")
        
        # 提取作品别名
        result["work"] = extract_work_aliases(filtered_subjects)
        logger.info(f"提取 {len(result['work'])} 个作品别名")
        
        # 收集 subject_id 列表
        valid_subject_ids = {s.get("id") for s in filtered_subjects if s.get("id")}
        logger.info(f"有效 subject_id 数量: {len(valid_subject_ids)}")
    
    # 2. 加载 subject-characters.jsonlines，通过 subject_id 找 character_id
    if "subject_characters" in files:
        logger.info(f"加载作品角色关联: {files['subject_characters']}")
        subject_chars = load_jsonlines(files["subject_characters"])
        logger.info(f"共 {len(subject_chars)} 条关联数据")
        
        # 筛选在有效 subject_id 中的记录
        filtered_subject_chars = [sc for sc in subject_chars if sc.get("subject_id") in valid_subject_ids]
        logger.info(f"筛选后的关联: {len(filtered_subject_chars)} 条")
        
        # 收集 character_id
        valid_character_ids = {sc.get("character_id") for sc in filtered_subject_chars if sc.get("character_id")}
        logger.info(f"有效 character_id 数量: {len(valid_character_ids)}")
    
    # 3. 加载 character.jsonlines，只保留在 character_id 清单中的角色
    if "character" in files:
        logger.info(f"加载角色数据: {files['character']}")
        all_chars = load_jsonlines(files["character"])
        logger.info(f"共 {len(all_chars)} 条角色数据")
        
        # 筛选
        filtered_chars = [c for c in all_chars if c.get("id") in valid_character_ids]
        logger.info(f"筛选后的角色: {len(filtered_chars)} 条")
        
        # 提取角色别名
        result["character"] = extract_character_aliases(filtered_chars)
        logger.info(f"提取 {len(result['character'])} 个角色别名")
    
    # 从 zip 加载
    if "zip" in files:
        if not valid_character_ids:
            logger.info(f"从 ZIP 加载: {files['zip']}")
            
            # 加载 subject
            subjects = load_json_from_zip(files["zip"], "subject")
            if subjects:
                filtered_subjects = [s for s in subjects if s.get("type") in [2, 4]]
                result["work"] = extract_work_aliases(filtered_subjects)
                valid_subject_ids = {s.get("id") for s in filtered_subjects if s.get("id")}
                logger.info(f"提取 {len(result['work'])} 个作品别名")
            
            # 加载 subject-characters
            subject_chars = load_json_from_zip(files["zip"], "subject-characters")
            if subject_chars:
                filtered_subject_chars = [sc for sc in subject_chars if sc.get("subject_id") in valid_subject_ids]
                valid_character_ids = {sc.get("character_id") for sc in filtered_subject_chars if sc.get("character_id")}
                logger.info(f"有效 character_id: {len(valid_character_ids)}")
            
            # 加载 character
            chars = load_json_from_zip(files["zip"], "character")
            if chars:
                filtered_chars = [c for c in chars if c.get("id") in valid_character_ids]
                result["character"] = extract_character_aliases(filtered_chars)
                logger.info(f"提取 {len(result['character'])} 个角色别名")
    
    logger.info(f"写入: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    total = len(result["character"]) + len(result["work"])
    logger.info(f"完成! 共 {total} 个别名 (角色: {len(result['character'])}, 作品: {len(result['work'])})")


if __name__ == "__main__":
    main()
