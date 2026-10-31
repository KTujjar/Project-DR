import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from camera.convert_raw10 import unpack_raw10, demosaic_rggb, estimate_gains, color_matrix, render, srgb_encode, main


class Raw10Tests(unittest.TestCase):
    def test_documented_bit_order_all_low_bit_positions_and_padding(self):
        first=bytes([0,0,0,255,0b11100100, 1,1,1,1,0b11100100])+bytes([0xa5]*6)
        second=bytes([128,64,32,16,0b00011011, 0,0,0,0,0])+bytes([0xff]*6)
        decoded=unpack_raw10(first+second,8,2,16)
        np.testing.assert_array_equal(decoded[0],[0,1,2,1023,4,5,6,7])
        np.testing.assert_array_equal(decoded[1],[515,258,129,64,0,0,0,0])

    def test_reject_truncation_bad_stride_and_odd_geometry(self):
        for data,w,h,s in ((b'0'*19,4,2,10),(b'0'*8,4,2,4),(b'0'*30,6,2,15)):
            with self.assertRaises(ValueError):unpack_raw10(data,w,h,s)

    def test_multiframe_selection(self):
        decoded=unpack_raw10(bytes(20)+bytes([255]*20),4,2,10,frame=1)
        self.assertTrue(np.all(decoded==1023))
        with self.assertRaises(ValueError):unpack_raw10(bytes(20),4,2,10,frame=1)

    def test_demosaic_preserves_channel_order_and_edges(self):
        mosaic=np.zeros((8,12),np.float32)
        mosaic[::2,::2]=.8;mosaic[::2,1::2]=.2;mosaic[1::2,::2]=.2;mosaic[1::2,1::2]=.05
        result=demosaic_rggb(mosaic)
        for i,value in enumerate((.8,.2,.05)):
            np.testing.assert_allclose(result[:,:,i],value,atol=1e-7)
        # Known measurements must survive interpolation, including a nonuniform mosaic.
        mosaic=np.arange(96,dtype=np.float32).reshape(8,12)
        result=demosaic_rggb(mosaic)
        np.testing.assert_array_equal(result[::2,::2,0],mosaic[::2,::2])
        np.testing.assert_array_equal(result[1::2,1::2,2],mosaic[1::2,1::2])

    def test_gray_world_recovers_neutral_patch_gains(self):
        mosaic=np.zeros((16,16),np.float32)
        mosaic[::2,::2]=.1;mosaic[::2,1::2]=.2;mosaic[1::2,::2]=.2;mosaic[1::2,1::2]=.05
        gains,count,note=estimate_gains(mosaic)
        np.testing.assert_allclose(gains,[2,1,4],atol=1e-6)
        self.assertEqual(count,64)
        gains,_,note=estimate_gains(np.zeros((16,16),np.float32))
        np.testing.assert_array_equal(gains,[1,1,1]);self.assertIn('Insufficient',note)

    def test_srgb_encoding_and_linear_ccm_rgb_order(self):
        np.testing.assert_allclose(srgb_encode(np.array([0,.0031308,.5,1])),[0,.04044994,.73535698,1],atol=1e-6)
        raw=np.zeros((8,8),np.uint16)
        raw[::2,::2]=800;raw[::2,1::2]=200;raw[1::2,::2]=200;raw[1::2,1::2]=50
        normal,_=render(raw,black=0,white=1000,wb='neutral',exposure='0')
        swap,_=render(raw,black=0,white=1000,wb='neutral',ccm=np.array([[0,0,1],[0,1,0],[1,0,0]],np.float32),exposure='0')
        np.testing.assert_array_equal(swap,normal[:,:,::-1])
        self.assertGreater(int(normal[0,0,0]),int(normal[0,0,2]))

    def test_color_matrix_validation(self):
        np.testing.assert_allclose(color_matrix('imx219',4650)[0],[2.18174,-.70887,-.47287],atol=1e-6)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ccm.json';path.write_text('[[1,0],[0,1]]')
            with self.assertRaises(ValueError):color_matrix(str(path),5000)

    def test_cli_creates_decodable_full_size_jpeg_profile_preview_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'frame.raw';output=Path(directory)/'frame.jpg'
            # Uniform 512-valued mosaic (4 samples -> high bytes 128, low bits zero).
            source.write_bytes(bytes([128,128,128,128,0]*2+[0xaa,0xaa])*8)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(source),str(output),'--width','8','--height','8','--stride','12']),0)
            with Image.open(output) as image:
                image.load();self.assertEqual(image.size,(8,8));self.assertEqual(image.mode,'RGB')
                self.assertTrue(image.info['icc_profile'])
            self.assertTrue(output.with_name('frame-preview.jpg').exists())
            report=json.loads(output.with_suffix('.jpg.json').read_text())
            self.assertEqual(report['row_padding_bytes'],2)
            self.assertEqual(report['raw_percentiles']['p50'],512)
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main([str(source),str(output),'--width','8','--height','8','--stride','12'])


if __name__=='__main__':unittest.main()
