/* Native V4L2 capture only. No ROS, controls, format changes, ISP or codec assumptions.
 * stdout: one JSON header line followed by exactly header.bytes raw bytes.
 * Existing sensor mode is configured separately by the approved operator launcher.
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
static volatile sig_atomic_t stopped=0;
static void stop(int sig){(void)sig;stopped=1;}
static double clocksec(clockid_t id){struct timespec t;clock_gettime(id,&t);return t.tv_sec+t.tv_nsec/1e9;}
static int xio(int fd,unsigned long request,void *arg){int r;do{r=ioctl(fd,request,arg);}while(r<0&&errno==EINTR&&!stopped);return r;}
static void fatal(const char *s){perror(s);exit(1);}
static int output(const void *data,size_t size){const char *p=data;while(size&&!stopped){ssize_t n=write(STDOUT_FILENO,p,size);if(n<0){if(errno==EINTR)continue;return -1;}p+=n;size-=n;}return stopped?-1:0;}
int main(int argc,char **argv){
 signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGPIPE,stop);
 const char *device=argc>1?argv[1]:"/dev/video0";int count=argc>2?atoi(argv[2]):0;
 int lockfd=open("/tmp/turtbot-camera.lock",O_CREAT|O_RDWR,0600);
 if(lockfd<0||flock(lockfd,LOCK_EX|LOCK_NB))fatal("camera worker already owns the camera");
 int fd=open(device,O_RDWR|O_NONBLOCK);if(fd<0)fatal(device);
 struct v4l2_format fmt={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE};if(xio(fd,VIDIOC_G_FMT,&fmt))fatal("G_FMT");
 if(fmt.fmt.pix.pixelformat!=V4L2_PIX_FMT_SRGGB10P){fprintf(stderr,"Expected pRAA; refusing unknown Bayer layout\n");return 2;}
 struct v4l2_requestbuffers req={.count=3,.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
 if(xio(fd,VIDIOC_REQBUFS,&req)||req.count<2||req.count>8)fatal("REQBUFS");
 void *maps[8]={0};size_t lengths[8]={0};
 for(unsigned i=0;i<req.count;i++){struct v4l2_buffer b={.type=req.type,.memory=req.memory,.index=i};if(xio(fd,VIDIOC_QUERYBUF,&b))fatal("QUERYBUF");lengths[i]=b.length;maps[i]=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd,b.m.offset);if(maps[i]==MAP_FAILED)fatal("mmap");if(xio(fd,VIDIOC_QBUF,&b))fatal("QBUF");}
 enum v4l2_buf_type type=req.type;if(xio(fd,VIDIOC_STREAMON,&type))fatal("STREAMON");
 unsigned delivered=0,last_seq=0;int had_seq=0;unsigned long dropped=0;
 while(!stopped&&(!count||delivered<(unsigned)count)){
  struct pollfd p={.fd=fd,.events=POLLIN};int ready=poll(&p,1,3000);if(ready<0&&errno==EINTR)continue;if(ready<=0){fprintf(stderr,"Camera timeout/disconnected\n");break;}
  struct v4l2_buffer b={.type=req.type,.memory=req.memory};if(xio(fd,VIDIOC_DQBUF,&b)){if(errno==EAGAIN)continue;perror("DQBUF");break;}
  /* Drain backlog, retaining the newest frame instead of accumulating latency. */
  for(;;){struct v4l2_buffer next={.type=req.type,.memory=req.memory};if(xio(fd,VIDIOC_DQBUF,&next)){if(errno!=EAGAIN&&errno!=EINTR)stopped=1;break;}if(xio(fd,VIDIOC_QBUF,&b))fatal("QBUF drain");b=next;}
  if(b.index>=req.count||b.bytesused>lengths[b.index]){fprintf(stderr,"Invalid buffer\n");break;}
  if(had_seq&&b.sequence>last_seq){dropped+=b.sequence-last_seq-1;}
  last_seq=b.sequence;had_seq=1;
  double source=b.timestamp.tv_sec+b.timestamp.tv_usec/1e6;
  int mono=(b.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK)==V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
  double captured=mono?source+clocksec(CLOCK_REALTIME)-clocksec(CLOCK_MONOTONIC):source;
  char header[1024];int n=snprintf(header,sizeof(header),"{\"protocol\":1,\"bytes\":%u,\"width\":%u,\"height\":%u,\"stride\":%u,\"format\":\"pRAA\",\"sequence\":%u,\"capture_unix\":%.6f,\"sent_unix\":%.6f,\"timestamp_clock\":\"%s\",\"timestamp_source\":\"%s\",\"source_dropped\":%lu,\"pid\":%d}\n",b.bytesused,fmt.fmt.pix.width,fmt.fmt.pix.height,fmt.fmt.pix.bytesperline,b.sequence,captured,clocksec(CLOCK_REALTIME),mono?"monotonic_mapped_to_pi_realtime":"device_realtime_unverified",(b.flags&V4L2_BUF_FLAG_TSTAMP_SRC_MASK)==V4L2_BUF_FLAG_TSTAMP_SRC_SOE?"start_of_exposure":"end_of_frame",dropped,getpid());
  if(n<=0||(size_t)n>=sizeof(header)||output(header,n)||output(maps[b.index],b.bytesused))break;
  delivered++;if(xio(fd,VIDIOC_QBUF,&b))break;
 }
 xio(fd,VIDIOC_STREAMOFF,&type);for(unsigned i=0;i<req.count;i++)munmap(maps[i],lengths[i]);close(fd);close(lockfd);return 0;
}
