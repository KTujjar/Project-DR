import io,json,tempfile,time,unittest,os
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from dashboard.backend.app import create_app
from camera.protocol import read_frame

class MissionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();root=Path(self.directory.name);self.token=root/'token';self.token.write_text('unit-test-only-token')
        self.env=patch.dict(os.environ,{'TURTBOT_TOKEN_FILE':str(self.token)});self.env.start()
        self.bridge=patch('dashboard.backend.ros_bridge.RosBridge');self.bridge.start()
        self.client=TestClient(create_app('hardware',root/'data'));self.client.__enter__()
        self.auth={'Authorization':'Bearer unit-test-only-token'}
    def tearDown(self):self.client.__exit__(None,None,None);self.bridge.stop();self.env.stop();self.directory.cleanup()
    def frame(self):
        image=io.BytesIO();Image.new('RGB',(16,12),(80,90,100)).save(image,format='JPEG')
        meta={'frame_id':'unit-frame-1','capture_unix':time.time(),'width':16,'height':12}
        return self.client.post('/api/internal/camera',content=image.getvalue(),headers={**self.auth,'X-Frame-Meta':json.dumps(meta)})
    def test_authentication_image_validation_and_provenance(self):
        self.assertEqual(self.client.post('/api/internal/camera',content=b'bad').status_code,401)
        self.assertEqual(self.frame().status_code,200)
        health=self.client.get('/api/health').json();self.assertTrue(health['camera_verified']);self.assertFalse(health['motion_enabled'])
        self.assertEqual(self.client.get('/api/camera').headers['x-sensor-provenance'],'hardware')
        self.assertEqual(self.client.post('/api/internal/camera',content=b'not jpeg',headers={**self.auth,'X-Frame-Meta':json.dumps({'frame_id':'bad','capture_unix':time.time()})}).status_code,422)
    def test_video_requires_matching_ack_and_serves_actual_bytes(self):
        self.frame()
        with self.client.websocket_connect('/ws/video',headers={'Origin':'http://testserver'}) as ws:
            meta=ws.receive_json();raw=ws.receive_bytes();self.assertEqual(meta['frame_id'],'unit-frame-1');self.assertTrue(raw.startswith(b'\xff\xd8'))
            ws.send_json({'frame_id':meta['frame_id']})
            import hashlib
            self.assertEqual(meta['jpeg_sha256'],hashlib.sha256(raw).hexdigest())
    def test_jpeg_integrity_mismatch_rejected(self):
        image=io.BytesIO();Image.new('RGB',(16,12)).save(image,format='JPEG')
        meta={'frame_id':'corrupt','capture_unix':time.time(),'width':16,'height':12,'jpeg_sha256':'0'*64}
        response=self.client.post('/api/internal/camera',content=image.getvalue(),headers={**self.auth,'X-Frame-Meta':json.dumps(meta)})
        self.assertEqual(response.status_code,422)
    def test_mission_annotations_snapshots_persistence_and_export(self):
        self.frame();event=self.client.post('/api/mission/events',json={'kind':'poi','note':'Check doorway'}).json()
        self.assertEqual(event['context']['camera']['data']['frame_id'],'unit-frame-1')
        capture=self.client.post('/api/snapshots').json();self.assertTrue(capture['camera_frame_available']);self.assertFalse(capture['synchronized'])
        self.assertEqual(len(self.client.get('/api/snapshots').json()['captures']),1)
        self.assertTrue(self.client.get('/api/mission/export').content.startswith(b'PK'))
        self.assertEqual(self.client.post('/api/mission/events',json={'note':''}).status_code,422)
    def test_model_contract_identity_expiry_and_no_movement(self):
        self.frame();p=self.client.get('/api/v1/perception/input',headers=self.auth).json();self.assertEqual(p['api_version'],'1.0')
        self.assertEqual(self.client.get(p['frame']['url'],headers=self.auth).status_code,200)
        result={'api_version':'1.0','model_id':'team-model','frame_id':'unit-frame-1','detections':[{'label':'object','confidence':.8,'bbox':[.1,.1,.3,.4]}]}
        response=self.client.post('/api/v1/perception/results',json=result,headers=self.auth)
        self.assertEqual(response.status_code,200);self.assertFalse(response.json()['movement_generated'])
        result['detections'][0]['bbox']=[.8,.8,.5,.5]
        self.assertEqual(self.client.post('/api/v1/perception/results',json=result,headers=self.auth).status_code,422)
        self.assertFalse(self.client.get('/api/health').json()['control']['armed'])
    def test_mock_overlay_is_explicit_and_never_motor_command(self):
        result=self.client.post('/api/v1/perception/mock').json();self.assertTrue(result['mock']);self.assertFalse(result['movement_generated'])
    def test_untrusted_host_rejected(self):
        self.assertEqual(self.client.get('/api/health',headers={'Host':'attacker.invalid'}).status_code,400)

    def test_map_is_honest_when_missing_and_exports_real_grid_when_present(self):
        self.assertFalse(self.client.get('/api/map').json()['available'])
        self.assertEqual(self.client.get('/api/map/image.png').status_code,503)
        self.client.app.state.store.occupancy_map={'width':2,'height':2,'resolution':.05,'frame_id':'map','data':[-1,0,50,100]}
        response=self.client.get('/api/map/image.png');self.assertEqual(response.status_code,200)
        with Image.open(io.BytesIO(response.content)) as image:self.assertEqual(image.size,(2,2))


class ProtocolTests(unittest.TestCase):
    def test_truncation_and_geometry_limits(self):
        h={'protocol':1,'bytes':4,'format':'pRAA','stride':2,'height':2}
        stream=io.BytesIO(json.dumps(h).encode()+b'\n1234');self.assertEqual(read_frame(stream)[1],b'1234')
        with self.assertRaises(EOFError):read_frame(io.BytesIO(json.dumps(h).encode()+b'\n1'))
        h['bytes']=17_000_000
        with self.assertRaises(ValueError):read_frame(io.BytesIO(json.dumps(h).encode()+b'\n'))
class DetectionMaskTests(unittest.TestCase):
    def test_polygon_mask_and_nonfinite_metadata_validation(self):
        from dashboard.backend.mission import validate_detections
        value={'api_version':'1.0','model_id':'segmentation','frame_id':'test','detections':[{'label':'region','confidence':.9,'mask':{'polygons':[[[.1,.1],[.4,.1],[.2,.5]]]}}]}
        self.assertEqual(len(validate_detections(value)['detections']),1)
        value['detections'][0]['metadata']={'unsafe':float('nan')}
        with self.assertRaises(ValueError):validate_detections(value)

if __name__=='__main__':unittest.main()
