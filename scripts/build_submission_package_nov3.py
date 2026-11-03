"""Freeze an allowlisted Nov3 v6 code/evidence tree; never open devices/network.

The verified v5 public tree is the immutable base. New workspace sources and
selected saved evidence are copied, anonymized and manifest-bound. Official
DOCX/PDF, signed forms, poster identities and complete raw camera archives are
delivered separately. Packaging is not a new hardware or accuracy test.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output/submission/working_20261102_v5/fpga_image_working'
HW = 'output/image_system_256x192/build_20261103_034450_utc_787ac48d'
FW = 'output/uart_firmware/build_20261103_034121_utc_0bc11cf3'
FW128 = 'output/uart_firmware/build_20261103_034121_utc_c1dec189'
LOAD = FW + '/hardware_20261103_040821_utc_68d1d4c6'
RES = ['output/uart_resolution/' + s for s in (
    'run_20261103_040835_utc_582b2e12', 'run_20261103_040847_utc_36f0b431',
    'run_20261103_040921_utc_e4ddd36f', 'run_20261103_041022_utc_a5050e45')]
GUI = 'output/uart_live/session_20261103_041128_616ad4b7'
MEASURE_OLD = 'output/uart_live/session_20261103_054712_2307f7b6'
MEASURE = 'output/uart_live/session_20261103_061909_79b28f3d'
DIGITAL = 'output/part_measurement/run_20261103_054519_utc_cf9eb476'
TEXT = {'.md','.txt','.json','.jsonl','.log','.rpt','.v','.sv','.xdc','.tcl',
        '.ps1','.py','.c','.h','.s','.ld','.hex','.csv','.html','.xml','.bda'}
RAW = {'.npy','.npz','.png','.jpg','.jpeg','.bin','.rgb','.gray','.hex'}
SCRIPTS = '''build_image_system.ps1 build_image_system.tcl build_uart_firmware.ps1
program_uart_firmware.ps1 check_uart_build_pair.py check_uart_elf_layout.py
simulate_image_axis.ps1 axis_reference.py filter_reference.py
check_uart_host_protocol.py check_uart_live_limits.py check_camera_preview_contract.py
check_uart_resolution_profiles.py test_uart_resolution.py check_part_measurement.py
check_part_measurement_gui.py test_part_measurement_hardware.py
build_submission_package_nov3.py verify_submission_package_nov3.py'''.split()
DOCS = ['docs/right_resolution_2026_11_03.md', 'docs/part_measurement_2026_11_03.md',
        'docs/update_v6.md', 'README.md', 'report/technical_report.md']
PROVENANCE = [
    'tmp/res256_upgrade/host_resolution_qa.json',
    'tmp/res256_upgrade/firmware_profiles_qa.json',
    'tmp/res256_upgrade/pair_review.json',
    'tmp/res256_upgrade/final_firmware_128_layout.json',
    'tmp/res256_upgrade/final_firmware_256_layout.json',
    'tmp/res256_upgrade/hardware_qa.json',
    'tmp/part_measurement/offline_geometry_qa.json',
    'tmp/part_measurement/gui_integration_close_gaps_qa.json',
    'tmp/part_measurement/calibration_attempt1.json',
    'tmp/part_measurement/physical_calibration_review.json',
    'tmp/part_measurement/physical_calibration_50mm_review.json',
    'tmp/part_measurement/physical_measurement_qa.json',
    'tmp/part_measurement/h_part_qa.json',
    'tmp/part_measurement/h_part_review.json',
    'tmp/part_measurement/h_part_live_original.jpg',
    'tmp/part_measurement/calibration_50mm_original.jpg']
NOTE = ('This selected anonymous package preserves original evidence identifiers. '
        'manifest.json binds packaged bytes separately from workspace source bytes. '
        'Numerical results and actual image/array bytes are unchanged; excluded '
        'local/private links are stated explicitly.\n\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def mapped(path):
    path = str(path).replace('\\', '/')
    return 'evidence/provenance/' + path[4:] if path.startswith('tmp/') else path


def identity_terms():
    # The private workspace's prior assembler already owns this review list.
    # Do not embed participant identities in a new published source file.
    prior = ROOT / 'scripts/build_submission_package.py'
    if prior.exists():
        for node in ast.parse(prior.read_text(encoding='utf-8-sig')).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SENSITIVE' for t in node.targets):
                return ast.literal_eval(node.value)
    return []


def clean_string(text, identities, map_tmp=True):
    text = text.replace(str(ROOT), '.').replace(ROOT.as_posix(), '.')
    text = re.sub(r"(?i)C:[/\\]+Users[/\\]+(?!\[user\]|<local_user>)[^/\\\s\"'<>]+", 'C:/Users/[user]', text)
    text = re.sub(r'\bDESKTOP-[A-Z0-9]+\b', '[host]', text)
    if map_tmp:
        text = text.replace('tmp/', 'evidence/provenance/').replace('tmp\\', 'evidence/provenance/')
    for term in identities[1:]:
        text = re.sub(re.escape(term), '[participant]', text, flags=re.I)
    return text


def clean_json(value, identities):
    if isinstance(value, dict):
        return {k: clean_json(v, identities) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_json(v, identities) for v in value]
    return clean_string(value, identities) if isinstance(value, str) else value


def markdown_links(text, relative, included):
    def change(match):
        label, link = match.group(1), match.group(2)
        if re.match(r'https?://|mailto:|#', link):
            return match.group(0)
        bare, _, anchor = link.partition('#')
        bare = bare.strip('<>')
        root_text = ROOT.as_posix()
        normalized = bare.replace('\\', '/')
        if normalized.startswith(root_text + '/'):
            target = normalized[len(root_text) + 1:]
        elif re.match(r'^[A-Za-z]:/', normalized):
            return label + '（本地文件未收入此匿名选集）'
        else:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), normalized))
        target = mapped(target)
        if target not in included:
            return label + '（该历史或独立交付文件未收入本选集）'
        new = posixpath.relpath(target, posixpath.dirname(mapped(relative)) or '.')
        return '[' + label + '](' + new + ('#' + anchor if anchor else '') + ')'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', change, text)


def collect():
    selected = set()
    def add(relative):
        p = ROOT / relative
        if not p.is_file():
            raise FileNotFoundError(relative)
        selected.add(Path(relative).as_posix())
    def tree(folder, suffixes):
        for p in sorted((ROOT / folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix.lower() in suffixes:
                add(p.relative_to(ROOT))
    tree('software', {'.py','.ps1','.txt'})
    tree('firmware/uart_image', {'.c','.s','.ld','.h'})
    for name in SCRIPTS:
        add('scripts/' + name)
    for name in DOCS + PROVENANCE:
        add(name)
    tree('output/axis/axis_256x192', TEXT | RAW)
    for name in ('image_system.bit','image_system.hwh','image_system.xsa','ps7_init.tcl',
                 'ps7_init.c','ps7_init.h','implementation_summary.txt','input_manifest.json',
                 'build_manifest.json','timing_summary.rpt','utilization.rpt','drc.rpt',
                 'check_timing.rpt','clock_utilization.rpt','route_status.rpt'):
        add(HW + '/' + name)
    for build in (FW, FW128):
        for name in ('manifest.json','uart_image.elf'):
            add(build + '/' + name)
    for name in ('build_pair.json','elf_layout.json','preflight.json','load.log'):
        add(LOAD + '/' + name)
    for folder in RES + [DIGITAL]:
        tree(folder, TEXT | RAW)
    for folder in (GUI, MEASURE_OLD, MEASURE):
        add(folder + '/result.json')
    summary = json.loads((ROOT / GUI / 'result.json').read_text())
    samples = []
    for mode in range(5):
        case = next(c for c in summary['cases'] if c['mode'] == mode)
        folder = GUI + '/frame%06d_mode%d' % (case['frame'], mode)
        tree(folder, TEXT | RAW)
        samples.append({'session':GUI.split('/')[-1], 'frame':case['frame'], 'mode':mode, 'directory':folder})
    for frame in (194, 1271, 1881):
        folder = MEASURE + '/frame%06d_mode2' % frame
        tree(folder, TEXT | RAW)
        samples.append({'session':MEASURE.split('/')[-1], 'frame':frame, 'mode':2, 'directory':folder})
    return selected, samples


def serialize(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def file_records(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and 'sha256' in value:
            yield value
        for item in value.values():
            yield from file_records(item)
    elif isinstance(value, list):
        for item in value:
            yield from file_records(item)


def make_package(output, base, rebuild, vivado):
    if output.exists():
        raise FileExistsError('Choose a new output directory: ' + str(output))
    base_manifest_raw = (base / 'manifest.json').read_bytes()
    base_manifest = json.loads(base_manifest_raw)
    data, lineage, transforms = {}, {}, {}
    for relative, record in base_manifest['files'].items():
        raw = (base / relative).read_bytes()
        if sha(raw) != record['sha256'] or len(raw) != record['bytes']:
            raise ValueError('Verified v5 base changed: ' + relative)
        data[relative] = raw
        lineage[relative] = {'source_path':relative, 'source_sha256':sha(raw), 'source_bytes':len(raw),
                            'source_kind':'verified_v5_package_copy'}
    selected, samples = collect()
    included = set(data) | {mapped(x) for x in selected} | {'evidence/selection_nov3.json','llm_logs/2026_11_03_session.md'}
    identities = identity_terms()
    for relative in sorted(selected):
        raw = (ROOT / relative).read_bytes()
        target = mapped(relative)
        clean = raw
        if Path(relative).suffix.lower() in TEXT:
            text = raw.decode('utf-8-sig')
            original_text = text
            if Path(relative).suffix.lower() == '.json':
                obj = json.loads(text)
                changed = clean_json(obj, identities)
                clean = raw if changed == obj else serialize(changed)
            else:
                if Path(relative).suffix.lower() == '.md':
                    text = markdown_links(text, relative, included)
                text = clean_string(text, identities, map_tmp=Path(relative).suffix.lower() in {'.md','.txt','.log','.rpt','.html','.xml'})
                clean = raw if text == original_text else text.encode('utf-8')
        data[target] = clean
        lineage[target] = {'source_path':target, 'source_sha256':sha(raw), 'source_bytes':len(raw),
                           'source_kind':'nov3_workspace_allowlist'}
        if clean != raw:
            transforms[target] = 'Local path/host anonymization and explicit selected-link mapping; numerical data unchanged'
    # The old UART/ARM comparison describes the old source revision. Preserve
    # those source bytes rather than rebinding old performance evidence to new
    # profile code that now occupies the same runtime paths.
    comparison_path = 'output/uart_transport_comparison_20261101.json'
    comparison = json.loads(data[comparison_path])
    previous_sources = []
    for rec in file_records(comparison):
        old_path = rec['path']
        if sha(data[old_path]) == rec['sha256'].lower():
            continue
        historical = (base / old_path).read_bytes()
        if sha(historical) != rec['sha256'].lower():
            raise ValueError('Historical comparison source cannot be preserved: ' + old_path)
        archived = 'evidence/previous_source_v5/' + old_path
        data[archived] = historical
        lineage[archived] = {'source_path':old_path,'source_sha256':sha(historical),
                            'source_bytes':len(historical),'source_kind':'verified_v5_historical_source'}
        rec['v5_package_path'] = old_path
        rec['path'] = archived
        previous_sources.append(archived)
    if previous_sources:
        comparison['v6_copy_note'] = 'Old comparison source bytes are archived separately; updated runtime paths are not old performance-test sources.'
        data[comparison_path] = serialize(comparison)
        transforms[comparison_path] = 'Relocate four original v5 source references to byte-identical historical snapshots; original timing/pixel/hash values preserved'
    # The implemented hardware gate validates package bytes, while retaining the
    # archived original source hashes. Do not weaken bit/ELF/PS-init pins.
    manifest_path = HW + '/build_manifest.json'
    bm = json.loads(data[manifest_path])
    for name, rec in bm['artifacts'].items():
        raw = data[HW + '/' + name]
        if rec['sha256'] != sha(raw) or rec['bytes'] != len(raw):
            rec['source_original_sha256'], rec['source_original_bytes'] = rec['sha256'], rec['bytes']
            rec.update(sha256=sha(raw), bytes=len(raw))
    if bm['input_manifest_sha256'] != sha(data[HW + '/input_manifest.json']):
        bm['source_original_input_manifest_sha256'] = bm['input_manifest_sha256']
        bm['input_manifest_sha256'] = sha(data[HW + '/input_manifest.json'])
    data[manifest_path] = serialize(bm)
    transforms[manifest_path] = 'Rebind anonymized artifact/input-manifest copies; preserve source_original identifiers and numeric implementation result'
    pair_path = LOAD + '/build_pair.json'
    pair = json.loads(data[pair_path])
    pair['source_original_hardware_manifest_sha256'] = pair['hardware_manifest_sha256']
    pair['hardware_manifest_sha256'] = sha(data[manifest_path])
    for name, rec in pair['artifacts'].items():
        raw = data[HW + '/' + name]
        if rec['sha256'] != sha(raw) or rec['bytes'] != len(raw):
            rec['source_original_sha256'], rec['source_original_bytes'] = rec['sha256'], rec['bytes']
            rec.update(sha256=sha(raw), bytes=len(raw))
    data[pair_path] = serialize(pair)
    transforms[pair_path] = 'Rebind packaged implemented-hardware manifest/artifacts; retain source_original identities'
    selection = {'version':'v6_20261103', 'base_manifest_sha256':sha(base_manifest_raw),
        'resolution_batches':RES, 'digital_measurement_batch':DIGITAL, 'gui_samples':samples,
        'gui_complete_summaries':[GUI, MEASURE_OLD, MEASURE], 'complete_gui_raw_archive_included':False,
        'measurement_session_final_count':2690,
        'measurement_geometry_status_counts':{'ok':1867,'truncated':735,'no_contour':88},
        'measurement_count_is_not_accuracy_count':True,
        'selected_physical_frames':[194,1271,1881], 'hardware_access_in_packaging':False,
        'previous_source_snapshots':previous_sources,
        'visible_chat_snapshot_unchanged':True, 'new_chat_export_added':False,
        'approved_screenshots':[mapped(p) for p in PROVENANCE if p.endswith('.jpg')]}
    data['evidence/selection_nov3.json'] = serialize(selection)
    data['llm_logs/2026_11_03_session.md'] = ('''# 2026年11月3日工程摘要

本文件是本轮工程回顾，不是逐字对话导出。保留原297条可见匿名消息快照及原截止时间；没有新增聊天导出、工具日志对话或内部推理。

完成显式256×192配置并保留128×96默认配置，RTL五模式仿真、50MHz完整实现、固件配对、固定图/相机各10次486168像素及348帧五模式GUI通过。新增电脑端轮廓/尺寸估计只使用已逐像素验证的FPGA Sobel输出，支持ROI、两点标定和独立叠加图。初次20mm短边标定的44.87mm长边偏差保留；独立50mm参照线后，标称40×20mm手画矩形约42.55×22.70mm，误差仍为毫米量级。H形实物示例约78.7×58.9mm，无独立真值，不作精度通过声明。

2690帧测量会话均通过FPGA像素核验，但几何结果包含1867有效、735截断、88无轮廓，包含摆放/调参，不是2690次准确测量。完整summary和选定代表数组单独声明。源码、报告与包版本更新不代表比赛上传；实物全景、视频、签署授权书和最终材料审核仍另行完成。
''').encode('utf-8')
    # Keep reviewed Markdown links valid after mapping, without silently adding
    # private files, forms or large archives to satisfy a link.
    for relative in list(data):
        if relative.endswith('.md'):
            cleaned = markdown_links(data[relative].decode('utf-8-sig'), relative, set(data))
            if cleaned.encode() != data[relative]:
                data[relative] = cleaned.encode()
                transforms[relative] = transforms.get(relative,'') + '; explicit excluded-link notes in selected publication copy'
    for relative, raw in data.items():
        if Path(relative).suffix.lower() in TEXT or Path(relative).name == 'LICENSE':
            text = raw.decode('utf-8-sig')
            for term in identities:
                allowed_removed = re.sub(r'https://github\.com/[^/\s)]+/pynq-z2-image-processing[^\s)\]]*', '', text)
                if term.casefold() in allowed_removed.casefold():
                    raise ValueError('Known identity remains in selected text: ' + relative)
            if re.search(r'C:[/\\]++Users[/\\]++(?!\[user\]|<local_user>)', text, flags=re.I):
                raise ValueError('Personal home path remains: ' + relative)
        elif Path(relative).suffix.lower() in {'.xsa','.hwh','.bit','.elf'}:
            for term in identities:
                if term.encode().lower() in raw.lower():
                    raise ValueError('Known identity in binary artifact: ' + relative)
            if relative.endswith('.xsa'):
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    assert z.testzip() is None
                    for name in z.namelist():
                        for term in identities:
                            if term.encode().lower() in z.read(name).lower():
                                raise ValueError('Known identity in XSA member: ' + name)
    output.mkdir(parents=True)
    bundle = output / 'fpga_image_working'
    bundle.mkdir()
    for relative, raw in sorted(data.items()):
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = {'schema_version':3, 'version':'v6_20261103',
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'status':'versioned_code_evidence_prepared_for_authorized_publication_not_competition_submission',
        'base_manifest_sha256':sha(base_manifest_raw), 'hardware_access_in_packaging':False,
        'official_report_delivered_separately':True, 'visible_chat_snapshot_unchanged':True,
        'exclusions':['official report DOCX/PDF','signed forms/identity poster','whole Git history',
                      'SD image/tool installers/vendor IP/venv/cache','unselected raw camera archives',
                      'private conversation/participant identity files'],
        'remaining':['full-system front and45degree photos','anonymous actual H264 video',
                     'signed official form','final competition upload and receipt'],
        'files':{p:{'sha256':sha(raw),'bytes':len(raw),**lineage.get(p,{}),
                    **({'transformation':transforms[p]} if p in transforms else {})}
                 for p,raw in sorted(data.items())}}
    (bundle / 'manifest.json').write_bytes(serialize(manifest))
    archive = output / 'fpga_image_working.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(bundle.rglob('*')):
            if p.is_file():
                z.write(p,p.relative_to(output).as_posix())
    checks = {}
    with tempfile.TemporaryDirectory(prefix='fpga_nov3_verify_') as td:
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            z.extractall(td)
        extracted = Path(td) / bundle.name
        for name in ['verify_submission_package_nov3.py','check_uart_host_protocol.py',
                     'check_uart_live_limits.py','check_camera_preview_contract.py',
                     'check_uart_resolution_profiles.py','check_part_measurement.py',
                     'check_part_measurement_gui.py']:
            run = subprocess.run([sys.executable,str(extracted/'scripts'/name)],cwd=extracted,
                                 capture_output=True,text=True,encoding='utf-8',errors='replace')
            checks[name] = {'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr}
            (output/(name+'.stdout.txt')).write_text(run.stdout,encoding='utf-8')
            (output/(name+'.stderr.txt')).write_text(run.stderr,encoding='utf-8')
            if run.returncode:
                raise RuntimeError('Extracted check failed: ' + name + '\n' + run.stdout + run.stderr)
        if rebuild:
            ps = shutil.which('pwsh')
            for w,h,expected in [(128,96,'f60d7dbdb7d0983e76acd46ed0aa59d28410240864cf7678bd51dda9fa788328'),
                                 (256,192,'9fb1becf183c475f5228062d576ecd684e0342af231dbcc24c090a6b1fc42ac9')]:
                run = subprocess.run([ps,'-NoProfile','-File',str(extracted/'scripts/build_uart_firmware.ps1'),
                    '-BaudRate','2000000','-Width',str(w),'-Height',str(h),'-VivadoBin',vivado],
                    cwd=extracted,capture_output=True,text=True,encoding='utf-8',errors='replace')
                marker = re.search(r'UART_FIRMWARE_BUILD=(.+)',run.stdout)
                if run.returncode or not marker:
                    raise RuntimeError('Offline firmware rebuild failed: ' + run.stdout + run.stderr)
                actual = sha((Path(marker.group(1).strip())/'uart_image.elf').read_bytes())
                if actual != expected:
                    raise ValueError('Recompiled firmware differs from passed ELF')
                checks['firmware_rebuild_%dx%d'%(w,h)] = {'passed':True,'elf_sha256':actual,'hardware_access':False}
    receipt = {'created_utc':datetime.now(timezone.utc).isoformat(),'all_checks_passed':True,
        'version':manifest['version'],'zip_sha256':sha(archive.read_bytes()),'zip_bytes':archive.stat().st_size,
        'payload_files':len(data),'total_files':len(data)+1,'hardware_access_in_this_audit':False,'checks':checks}
    (output/'package_qa.json').write_bytes(serialize(receipt))
    print(json.dumps({'zip':str(archive),'sha256':receipt['zip_sha256'],'payload_files':len(data),
                      'total_files':len(data)+1,'bytes':receipt['zip_bytes'],'qa_passed':True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'output/submission/working_20261103_v6')
    parser.add_argument('--base-directory',type=Path,default=BASE)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--verify-firmware-rebuild',action='store_true')
    parser.add_argument('--vivado-bin',default=r'E:\sailingsi\Vivado\2020.2\bin')
    args = parser.parse_args()
    if args.check_only:
        selected,samples = collect()
        print(json.dumps({'selected_new_source_files':len(selected),'new_gui_raw_samples':len(samples),'hardware_access':False}))
    else:
        make_package(args.output.resolve(),args.base_directory.resolve(),args.verify_firmware_rebuild,args.vivado_bin)


if __name__ == '__main__':
    main()
