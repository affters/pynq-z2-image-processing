"""Offline v6 integrity, saved pixels, profile pairing and geometry audit.

Never opens cameras/UART/JTAG. It rechecks archived evidence, not new hardware.
Full GUI summaries are retained; only explicitly selected pixel arrays are in
the distribution. No measurement-accuracy pass is inferred from pixel equality.
"""
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import zlib

import numpy as np
from PIL import Image

import verify_submission_package_nov2 as prior
from check_uart_build_pair import validate_pair
from test_uart_resolution import scalar_reference

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'software'))
from image_reference import process_reference
from part_measurement import analyze_edges


def read(relative):
    return json.loads((ROOT/relative).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def close(a,b):
    assert math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-5),(a,b)


def verify_case(directory,case):
    path = ROOT/directory
    with np.load(path/'pixels.npz',allow_pickle=False) as saved:
        rgb,actual = saved['rgb'],saved['actual']
        expected = process_reference(rgb,case['mode'])
        assert rgb.shape==(192,256,3) and rgb.dtype==np.uint8
        assert np.array_equal(expected,scalar_reference(rgb,case['mode']))
        assert actual.dtype==np.uint8 and np.array_equal(actual,expected)
        assert np.array_equal(saved['expected'],expected) and not saved['difference'].any()
        assert list(actual.shape)==case['output_shape']
        assert actual.size==case['response_payload_bytes']
        assert zlib.crc32(actual.tobytes())&0xffffffff==case['response_crc32']
        assert case['exact_match'] and case['mismatch_pixels']==case['max_abs_error']==0
        if 'input_rgb_sha256' in case:
            assert hashlib.sha256(rgb.tobytes()).hexdigest()==case['input_rgb_sha256']
        for name,array in [('input',rgb),('actual',actual),('expected',expected)]:
            assert np.array_equal(np.asarray(Image.open(path/(name+'.png'))),array)
        if (path/'actual.gray').exists():
            assert (path/'actual.gray').read_bytes()==actual.tobytes()
        return actual.copy()


def metadata(record):
    settings,result = record['settings'],record['result']
    assert record['source']=='verified_fpga_sobel' and record['computation']=='host'
    assert record['settings_version']==settings['version']
    assert result['measurement_location']=='host_after_verified_fpga_sobel'
    assert result['roi']==(settings['roi'] or [0,0,254,190])
    if settings['mm_per_pixel'] is None:
        assert result['long_mm'] is result['short_mm'] is None
    else:
        distance=math.dist(*settings['calibration_points'])
        assert distance>=8
        close(settings['mm_per_pixel'],settings['calibration_known_mm']/distance)
        close(result['mm_per_pixel'],settings['mm_per_pixel'])
    if result['status']=='ok':
        assert result['long_px']>=result['short_px']>0
        assert not result['selected_contour']['touches_boundary']
        if settings['mm_per_pixel'] is not None:
            close(result['long_mm'],result['long_px']*settings['mm_per_pixel'])
            close(result['short_mm'],result['short_px']*settings['mm_per_pixel'])
    else:
        assert result['status'] in ('no_contour','truncated')
        assert all(result[name] is None for name in ('long_px','short_px','long_mm','short_mm'))


def review_range(summary,path,version,count):
    review=read(path)
    lo,hi=review.get('reviewed_range',review.get('frame_range_observed'))
    cases=[c for c in summary['cases'] if lo<=c['frame']<=hi]
    assert len(cases)==count==hi-lo+1
    measurements=[c['measurement'] for c in cases]
    assert all(m['settings_version']==version for m in measurements)
    assert Counter(m['result']['status'] for m in measurements)==review['status_counts']
    assert not review.get('physical_accuracy_pass',False)
    return {'range':[lo,hi],'records':count,'status_counts':dict(Counter(m['result']['status'] for m in measurements))}


def main():
    captured=io.StringIO()
    with redirect_stdout(captured):
        prior.main()
    legacy_result=json.loads(captured.getvalue())
    selection=read('evidence/selection_nov3.json')
    assert selection['version']=='v6_20261103' and not selection['hardware_access_in_packaging']
    batches=[]
    for folder in selection['resolution_batches']:
        result=read(folder+'/result.json')
        assert result['requested_action_passed'] and result['error'] is None and result['cleanup_errors']==[]
        assert (result['width'],result['height'])==(256,192)
        assert result['firmware_info']=='pynq_uart_image_256x192_v1'
        total=0
        for case in result['cases']:
            actual=verify_case(folder+'/frame%d_mode%d'%(case['frame'],case['mode']),case)
            total+=actual.size
        assert total==result['actual_output_pixels']
        assert len(result['cases'])==result['actual_fpga_frames_verified']
        batches.append({'source':result['source'],'frames':len(result['cases']),'pixels':total})
    assert [b['pixels'] for b in batches]==[0,49152,486168,486168]
    digital=read(selection['digital_measurement_batch']+'/result.json')
    assert digital['requested_action_passed'] and digital['error'] is None and digital['cleanup_errors']==[]
    assert digital['actual_output_pixels']==96520 and not digital['physical_accuracy_verified']
    for case in digital['cases']:
        folder=selection['digital_measurement_batch']+'/frame%d_mode2'%case['frame']
        actual=verify_case(folder,case)
        measured=read(folder+'/measurement.json')
        assert measured['status']==('ok' if case['frame']==0 else 'no_contour')
        current=analyze_edges(actual)
        assert current['status']==measured['status']
        if case['frame']==0:
            close(current['long_px'],129);close(current['short_px'],65)
        else:
            assert current['long_mm'] is current['short_mm'] is None
    summaries={}
    for folder,count in zip(selection['gui_complete_summaries'],(348,1378,2690)):
        result=read(folder+'/result.json')
        assert len(result['cases'])==count
        assert result['error'] is None and result['cleanup_errors']==[]
        assert all(c['exact_match'] and c['mismatch_pixels']==c['max_abs_error']==0 for c in result['cases'])
        summaries[folder]=result
    five=summaries[selection['gui_complete_summaries'][0]]
    assert five['all_modes_verified'] and Counter(c['mode'] for c in five['cases'])=={0:64,1:90,2:71,3:53,4:70}
    measurement=summaries[selection['gui_complete_summaries'][2]]
    assert len([c for c in measurement['cases'] if 'measurement' in c])==2690
    statuses=Counter(c['measurement']['result']['status'] for c in measurement['cases'])
    assert statuses==selection['measurement_geometry_status_counts']
    for summary in list(summaries.values())[1:]:
        for case in summary['cases']:
            metadata(case['measurement'])
    for sample in selection['gui_samples']:
        folder='output/uart_live/'+sample['session']
        case=next(c for c in summaries[folder]['cases'] if c['frame']==sample['frame'] and c['mode']==sample['mode'])
        actual=verify_case(sample['directory'],case)
        if 'measurement' in case:
            record=read(sample['directory']+'/measurement.json')
            assert record==case['measurement']
            settings=record['settings']
            result=analyze_edges(actual,roi=settings['roi'],threshold=settings['threshold'],
                min_area=settings['min_area'],mm_per_pixel=settings['mm_per_pixel'],
                close_gaps=settings.get('close_gaps',True))
            for key in ('status','long_px','short_px','long_mm','short_mm'):
                if isinstance(result[key],(int,float)):
                    close(result[key],record['result'][key])
                else:
                    assert result[key]==record['result'][key]
    ranges=[]
    for filename,version,count in [('physical_calibration_review.json',8,350),
                                   ('physical_calibration_50mm_review.json',15,30),
                                   ('h_part_review.json',17,20)]:
        ranges.append(review_range(measurement,'evidence/provenance/part_measurement/'+filename,version,count))
    hw='output/image_system_256x192/build_20261103_034450_utc_787ac48d'
    fw='output/uart_firmware/build_20261103_034121_utc_0bc11cf3'
    pair=validate_pair(ROOT/fw,ROOT/hw)
    assert pair['pair_validated'] and pair['image_width']==256 and pair['image_height']==192
    with tempfile.TemporaryDirectory(prefix='fpga_pair_audit_') as td:
        output=Path(td)/'pair.json'
        run=subprocess.run([sys.executable,str(ROOT/'scripts/check_uart_build_pair.py'),str(ROOT/fw),str(ROOT/hw),str(output)],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        assert run.returncode==0,(run.stdout,run.stderr)
        assert json.loads(output.read_text())['pair_validated']
    assert sha(hw+'/image_system.bit')=='5c5f834d520717ea27782cc4f84ba5b8339e02e11dc12eb4b0eaccea842f702e'
    assert sha(hw+'/ps7_init.tcl')=='05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b'
    assert sha(fw+'/uart_image.elf')=='9fb1becf183c475f5228062d576ecd684e0342af231dbcc24c090a6b1fc42ac9'
    firmware=read(fw+'/manifest.json')
    for name,expected in firmware['source_hashes'].items():
        assert sha('firmware/uart_image/'+name)==expected.lower()
    bm=read(hw+'/build_manifest.json')
    assert bm['input_manifest_sha256']==sha(hw+'/input_manifest.json')
    axis='output/axis/axis_256x192'
    values=np.array([int(x,16) for x in (ROOT/axis/'input_rgb.hex').read_text().split()],dtype=np.uint32)
    rgb=np.stack([(values>>16)&255,(values>>8)&255,values&255],axis=-1).astype(np.uint8).reshape(192,256,3)
    for mode in range(5):
        actual=np.array([int(x,16) for x in (ROOT/axis/('rtl_axis_mode%d.hex'%mode)).read_text().split()],dtype=np.uint8)
        assert np.array_equal(actual,scalar_reference(rgb,mode).ravel())
    chat=read('llm_logs/conversation_submission_anonymous_manifest.json')
    assert chat['messages']==297 and chat['user_messages']==96 and chat['assistant_messages']==201
    print(json.dumps({'all_passed':True,'version':'v6_20261103','legacy_checks':legacy_result,
        'resolution_batches':batches,'axis_256_modes_verified':5,'digital_measurement_pixels':96520,
        'gui_summary_frames':[348,1378,2690],'measurement_status_counts':dict(statuses),
        'selected_new_gui_raw_samples_verified':len(selection['gui_samples']),'measurement_review_ranges':ranges,
        'manifest_bound_256_pair_cli_passed':True,'physical_accuracy_claimed':False,
        'visible_chat_messages_unchanged':297,'hardware_access_in_this_audit':False},indent=2))


if __name__=='__main__':
    main()
