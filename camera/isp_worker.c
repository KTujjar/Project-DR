/* Existing V4L2 camera -> BCM2835 ISP -> fixed-quality hardware JPEG encoder.
 * No new drivers, ROS, boot changes, or automatic motion. Raw worker remains fallback.
 * stdout protocol matches capture_worker v1, with format=JPEG.
 */
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <math.h>
#include "metering.h"
#ifndef V4L2_CID_USER_BCM2835_ISP_BASE
#define V4L2_CID_USER_BCM2835_ISP_BASE 0x009819e0
#endif
#include "vendor/bcm2835-isp.h"
_Static_assert(sizeof(struct bcm2835_isp_black_level)==12,"ISP black-level ABI changed");
_Static_assert(sizeof(struct bcm2835_isp_custom_ccm)==88,"ISP CCM ABI changed");
_Static_assert(sizeof(struct bcm2835_isp_gamma)==136,"ISP gamma ABI changed");
static volatile sig_atomic_t stopped=0;
static void onstop(int s){(void)s;stopped=1;}
static void die(const char*s){perror(s);exit(1);}
static int xio(int fd,unsigned long r,void*a){int n;do{n=ioctl(fd,r,a);}while(n<0&&errno==EINTR&&!stopped);return n;}
static double now(clockid_t id){struct timespec t;clock_gettime(id,&t);return t.tv_sec+t.tv_nsec/1e9;}
static int writeall(const void*data,size_t size){const char*p=data;while(size&&!stopped){ssize_t n=write(1,p,size);if(n<0){if(errno==EINTR)continue;return -1;}p+=n;size-=n;}return stopped?-1:0;}
struct queue{int fd,multi,on;enum v4l2_buf_type type;unsigned width,height,stride,size,count;void*map[4];unsigned length[4];};
static struct queue queue_init(int fd,enum v4l2_buf_type type,unsigned w,unsigned h,unsigned format,unsigned stride){
 struct queue q={.fd=fd,.type=type,.multi=V4L2_TYPE_IS_MULTIPLANAR(type)};
 struct v4l2_format f={.type=type};
 if(q.multi){f.fmt.pix_mp.width=w;f.fmt.pix_mp.height=h;f.fmt.pix_mp.pixelformat=format;f.fmt.pix_mp.num_planes=1;f.fmt.pix_mp.field=V4L2_FIELD_NONE;f.fmt.pix_mp.plane_fmt[0].bytesperline=stride;}
 else{f.fmt.pix.width=w;f.fmt.pix.height=h;f.fmt.pix.pixelformat=format;f.fmt.pix.field=V4L2_FIELD_NONE;f.fmt.pix.bytesperline=stride;}
 if(xio(fd,VIDIOC_S_FMT,&f))die("S_FMT queue");
 q.width=q.multi?f.fmt.pix_mp.width:f.fmt.pix.width;q.height=q.multi?f.fmt.pix_mp.height:f.fmt.pix.height;
 q.stride=q.multi?f.fmt.pix_mp.plane_fmt[0].bytesperline:f.fmt.pix.bytesperline;q.size=q.multi?f.fmt.pix_mp.plane_fmt[0].sizeimage:f.fmt.pix.sizeimage;
 if((q.multi?f.fmt.pix_mp.pixelformat:f.fmt.pix.pixelformat)!=format){fprintf(stderr,"Driver changed pixel format; refusing\n");exit(2);}
 struct v4l2_requestbuffers r={.count=3,.type=type,.memory=V4L2_MEMORY_MMAP};if(xio(fd,VIDIOC_REQBUFS,&r)||r.count>4||r.count<2)die("REQBUFS queue");q.count=r.count;
 for(unsigned i=0;i<q.count;i++){
  struct v4l2_plane p[VIDEO_MAX_PLANES]={0};struct v4l2_buffer b={.type=type,.memory=V4L2_MEMORY_MMAP,.index=i};if(q.multi){b.m.planes=p;b.length=VIDEO_MAX_PLANES;}
  if(xio(fd,VIDIOC_QUERYBUF,&b)){die("QUERYBUF queue");}
  q.length[i]=q.multi?p[0].length:b.length;
  q.map[i]=mmap(NULL,q.length[i],PROT_READ|PROT_WRITE,MAP_SHARED,fd,q.multi?p[0].m.mem_offset:b.m.offset);if(q.map[i]==MAP_FAILED)die("mmap queue");
 }
 return q;
}
static void enqueue(struct queue*q,unsigned index,unsigned bytes){
 struct v4l2_plane p[VIDEO_MAX_PLANES]={0};struct v4l2_buffer b={.type=q->type,.memory=V4L2_MEMORY_MMAP,.index=index,.bytesused=bytes};
 if(q->multi){b.m.planes=p;b.length=1;p[0].bytesused=bytes;p[0].length=q->length[index];}
 if(xio(q->fd,VIDIOC_QBUF,&b))die("QBUF queue");
}
static struct v4l2_buffer dequeue(struct queue*q,unsigned*bytes){
 struct pollfd poller={.fd=q->fd,.events=V4L2_TYPE_IS_OUTPUT(q->type)?POLLOUT:POLLIN};
 for(;;){
  struct v4l2_plane p[VIDEO_MAX_PLANES]={0};struct v4l2_buffer b={.type=q->type,.memory=V4L2_MEMORY_MMAP};if(q->multi){b.m.planes=p;b.length=VIDEO_MAX_PLANES;}
  if(!xio(q->fd,VIDIOC_DQBUF,&b)){if(b.index>=q->count)die("invalid queue index");*bytes=q->multi?p[0].bytesused:b.bytesused;if(*bytes>q->length[b.index])die("invalid bytesused");return b;}
  if(stopped){exit(0);}
  if(errno!=EAGAIN){die("DQBUF queue");}
  struct timespec pause={.tv_sec=0,.tv_nsec=500000};nanosleep(&pause,NULL);
  int r=poll(&poller,1,2500);if(r<=0)die("queue timeout");
 }
}
static void streamon(struct queue*q){if(!q->on){if(xio(q->fd,VIDIOC_STREAMON,&q->type))die("STREAMON queue");q->on=1;}}
static void capture_start(struct queue*q){for(unsigned i=0;i<q->count;i++)enqueue(q,i,0);streamon(q);}
static void cleanup(struct queue*q){if(q->on)xio(q->fd,VIDIOC_STREAMOFF,&q->type);for(unsigned i=0;i<q->count;i++)munmap(q->map[i],q->length[i]);}
static int dev(const char*p){int fd=open(p,O_RDWR|O_NONBLOCK);if(fd<0)die(p);return fd;}
static void control(int fd,unsigned id,int value){struct v4l2_control c={.id=id,.value=value};if(xio(fd,VIDIOC_S_CTRL,&c))die("S_CTRL ISP");}
static void compound(int fd,unsigned id,void*data,unsigned size){struct v4l2_ext_control c={.id=id,.size=size,.ptr=data};struct v4l2_ext_controls cs={.count=1,.controls=&c};if(xio(fd,VIDIOC_S_EXT_CTRLS,&cs))die("S_EXT_CTRLS ISP");}
static int getcontrol(int fd,unsigned id){struct v4l2_control c={.id=id};if(xio(fd,VIDIOC_G_CTRL,&c))die("G_CTRL sensor");return c.value;}
static double pixelrate(int fd){struct v4l2_ext_control c={.id=V4L2_CID_PIXEL_RATE};struct v4l2_ext_controls cs={.count=1,.controls=&c};if(xio(fd,VIDIOC_G_EXT_CTRLS,&cs))die("G_EXT_CTRLS pixel rate");return c.value64;}
int main(int argc,char**argv){
 signal(SIGINT,onstop);signal(SIGTERM,onstop);signal(SIGPIPE,onstop);
 int filemode=argc>1&&!strcmp(argv[1],"--file"),frames=filemode?1:(argc>1?atoi(argv[1]):0);
 int lockfd=-1,camfd=-1;unsigned sw=640,sh=480,stride=800;struct queue cam={0};unsigned char*fixture=NULL;
 if(filemode){FILE*f=fopen(argv[2],"rb");if(!f)die("fixture");fixture=malloc(stride*sh);if(fread(fixture,1,stride*sh,f)!=stride*sh)die("fixture size");fclose(f);}
 else{
  lockfd=open("/tmp/turtbot-camera.lock",O_CREAT|O_RDWR,0600);if(lockfd<0||flock(lockfd,LOCK_EX|LOCK_NB))die("Camera owned by another worker");
  camfd=dev("/dev/video0");struct v4l2_format f={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE};if(xio(camfd,VIDIOC_G_FMT,&f))die("camera G_FMT");
  if(f.fmt.pix.pixelformat!=V4L2_PIX_FMT_SRGGB10P){fprintf(stderr,"Expected pRAA\n");return 2;}sw=f.fmt.pix.width;sh=f.fmt.pix.height;stride=f.fmt.pix.bytesperline;
  cam=queue_init(camfd,V4L2_BUF_TYPE_VIDEO_CAPTURE,sw,sh,V4L2_PIX_FMT_SRGGB10P,stride);
 }
 unsigned w=sw==1920?1280:sw==1640?1280:640,h=sw==1920?720:sw==1640?960:480;
 int inputfd=dev("/dev/video13"),rgbfd=dev("/dev/video14"),encoderfd=dev("/dev/video31"),sensorfd=-1;
 int exposure=0,gain=0,max_exposure=0;double line_ms=0,last_meter=-1,red=1.3,blue=2.25;
 if(!filemode){sensorfd=dev("/dev/v4l-subdev0");exposure=getcontrol(sensorfd,V4L2_CID_EXPOSURE);gain=getcontrol(sensorfd,V4L2_CID_ANALOGUE_GAIN);line_ms=(sw+getcontrol(sensorfd,V4L2_CID_HBLANK))/pixelrate(sensorfd)*1000.;max_exposure=fmin(sh+getcontrol(sensorfd,V4L2_CID_VBLANK)-4,33333./(line_ms*1000.));}
 struct queue input=queue_init(inputfd,V4L2_BUF_TYPE_VIDEO_OUTPUT,sw,sh,V4L2_PIX_FMT_SRGGB10P,stride);
 struct queue rgb=queue_init(rgbfd,V4L2_BUF_TYPE_VIDEO_CAPTURE,w,h,V4L2_PIX_FMT_RGB24,0);
 struct queue encoded_input=queue_init(encoderfd,V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,w,h,V4L2_PIX_FMT_RGB24,rgb.stride);
 struct queue encoded=queue_init(encoderfd,V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,w,h,V4L2_PIX_FMT_JPEG,0);
 /* Existing still-image encoder supports fixed quality; the video MJPEG
  * encoder varied quantization with bitrate and visibly discarded detail. */
 control(encoderfd,V4L2_CID_JPEG_COMPRESSION_QUALITY,92);
 struct bcm2835_isp_black_level black={.enabled=1,.black_level_r=4096,.black_level_g=4096,.black_level_b=4096};compound(inputfd,V4L2_CID_USER_BCM2835_ISP_BLACK_LEVEL,&black,sizeof(black));
 struct bcm2835_isp_custom_ccm ccm={.enabled=1};double matrix[9]={2.2229345,-.75967215,-.46326238,-.68348938,2.71188164,-1.02839935,-.26137462,-.66801596,1.92939055};
 for(unsigned i=0;i<9;i++){ccm.ccm.ccm[i/3][i%3].num=lround(matrix[i]*100000);ccm.ccm.ccm[i/3][i%3].den=100000;}compound(inputfd,V4L2_CID_USER_BCM2835_ISP_CC_MATRIX,&ccm,sizeof(ccm));
 struct bcm2835_isp_gamma gamma={.enabled=1};for(unsigned i=0;i<33;i++){double x=(i/32.)*(i/32.);gamma.x[i]=lround(x*65535);gamma.y[i]=lround((x<=.0031308?12.92*x:1.055*pow(x,1/2.4)-.055)*65535);}gamma.x[32]=gamma.y[32]=65535;compound(inputfd,V4L2_CID_USER_BCM2835_ISP_GAMMA,&gamma,sizeof(gamma));
 /* Unity viewing gain: sensor exposure is managed separately. A fixed 7x
  * multiplier here clipped usable RAW highlights before JPEG encoding. */
 control(inputfd,V4L2_CID_RED_BALANCE,lround(red*1000));control(inputfd,V4L2_CID_BLUE_BALANCE,lround(blue*1000));control(inputfd,V4L2_CID_DIGITAL_GAIN,1000);
 capture_start(&rgb);capture_start(&encoded);if(!filemode)capture_start(&cam);
 unsigned last=0,had=0;unsigned long dropped=0;int n=0;
 while(!stopped&&(!frames||n<frames)){
  unsigned bytes=stride*sh;struct v4l2_buffer c={0};double captured=now(CLOCK_REALTIME);
  if(!filemode){
   c=dequeue(&cam,&bytes);
   for(;;){struct v4l2_buffer next={.type=cam.type,.memory=V4L2_MEMORY_MMAP};if(xio(cam.fd,VIDIOC_DQBUF,&next)){if(errno!=EAGAIN&&errno!=EINTR)die("camera drain");break;}enqueue(&cam,c.index,0);c=next;bytes=c.bytesused;}
   captured=c.timestamp.tv_sec+c.timestamp.tv_usec/1e6+now(CLOCK_REALTIME)-now(CLOCK_MONOTONIC);
  }
  if(bytes>input.length[0]){die("ISP input buffer too small");}
  const unsigned char *raw=filemode?fixture:cam.map[c.index];struct camera_meter meter=meter_raw(raw,sw,sh,stride);
  double metered_at=now(CLOCK_MONOTONIC);
  if(filemode||last_meter<0||metered_at-last_meter>=.5){
   if(meter.wb_cells>=64){double weight=last_meter<0?1.:.2;red=red*(1-weight)+meter.red*weight;blue=blue*(1-weight)+meter.blue*weight;control(inputfd,V4L2_CID_RED_BALANCE,lround(red*1000));control(inputfd,V4L2_CID_BLUE_BALANCE,lround(blue*1000));}
   if(!filemode&&n>=3){
    double product=exposure*256./(256-gain)*meter_exposure_ratio(meter);
    exposure=lround(meter_clamp(product,4,max_exposure));gain=lround(256.-256./meter_clamp(product/exposure,1.,4.));
    control(sensorfd,V4L2_CID_EXPOSURE,exposure);control(sensorfd,V4L2_CID_ANALOGUE_GAIN,gain);
   }
   last_meter=metered_at;
  }
  memcpy(input.map[0],raw,bytes);enqueue(&input,0,bytes);streamon(&input);if(!filemode)enqueue(&cam,c.index,0);
  unsigned rgbbytes=0;struct v4l2_buffer r=dequeue(&rgb,&rgbbytes);
  unsigned inputbytes=0;dequeue(&input,&inputbytes);
  if(rgbbytes>encoded_input.length[0]){die("Encoder input buffer too small");}
  memcpy(encoded_input.map[0],rgb.map[r.index],rgbbytes);enqueue(&rgb,r.index,0);enqueue(&encoded_input,0,rgbbytes);streamon(&encoded_input);
  unsigned length=0;struct v4l2_buffer e=dequeue(&encoded,&length);
  unsigned consumed=0;dequeue(&encoded_input,&consumed);
  if(!filemode){if(had&&c.sequence>last)dropped+=c.sequence-last-1;last=c.sequence;had=1;}
  if(length<4||((unsigned char*)encoded.map[e.index])[0]!=0xff){fprintf(stderr,"Encoder did not produce JPEG\n");return 3;}
  char header[1800];int len=snprintf(header,sizeof(header),"{\"protocol\":1,\"bytes\":%u,\"width\":%u,\"height\":%u,\"stride\":0,\"format\":\"JPEG\",\"sequence\":%u,\"capture_unix\":%.6f,\"sent_unix\":%.6f,\"source_width\":%u,\"source_height\":%u,\"source_dropped\":%lu,\"pid\":%d,\"timestamp_clock\":\"monotonic_mapped_to_pi_realtime\",\"timestamp_source\":\"end_of_frame\",\"isp_digital_gain\":1.0,\"jpeg_quality\":92,\"encoder_device\":\"/dev/video31\",\"white_balance_gains_rgb\":[%.4f,1,%.4f],\"auto_exposure\":%s,\"requested_exposure_ms\":%.4f,\"requested_analogue_gain\":%.4f,\"raw_green_median\":%.4f,\"raw_green_p98\":%.4f,\"raw_saturated_fraction\":%.6f}\n",length,w,h,filemode?(unsigned)n:c.sequence,captured,now(CLOCK_REALTIME),sw,sh,dropped,getpid(),red,blue,filemode?"false":"true",exposure*line_ms,256./(256-gain),meter.median,meter.p98,meter.saturated);
  if(len<=0||(size_t)len>=sizeof(header)){fprintf(stderr,"Frame metadata overflow\n");return 3;}
  if(writeall(header,len)||writeall(encoded.map[e.index],length)){break;}
  enqueue(&encoded,e.index,0);n++;
 }
 if(!filemode){cleanup(&cam);}
 cleanup(&input);cleanup(&rgb);cleanup(&encoded_input);cleanup(&encoded);close(inputfd);close(rgbfd);close(encoderfd);if(sensorfd>=0)close(sensorfd);if(camfd>=0)close(camfd);if(lockfd>=0)close(lockfd);free(fixture);return 0;
}
