import rclpy,time,json
from sensor_msgs.msg import LaserScan,BatteryState,Imu
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
rclpy.init();n=rclpy.create_node('mission_verify');counts={};latest={}
def sample(p,m):
 counts[p]=counts.get(p,0)+1
 if p=='/scan':latest[p]={'valid':sum(1 for x in m.ranges if m.range_min<=x<=m.range_max),'samples':len(m.ranges)}
 elif p=='/battery_state':latest[p]={'voltage':m.voltage}
subs=[n.create_subscription(t,p,lambda m,p=p:sample(p,m),qos_profile_sensor_data) for p,t in [('/scan',LaserScan),('/odom',Odometry),('/imu',Imu),('/battery_state',BatteryState)]]
start=time.monotonic()
while time.monotonic()-start<10:rclpy.spin_once(n,timeout_sec=.1)
print(json.dumps({'elapsed':time.monotonic()-start,'counts':counts,'latest':latest,'nodes':n.get_node_names(),'cmd_vel_publishers':n.count_publishers('/cmd_vel')}));n.destroy_node();rclpy.shutdown()
