/* Small RAW10 meter. No image enhancement: controls capture exposure and WB.
 * Shared with the host-side numeric tests; no Linux or ROS dependencies. */
#ifndef TURTBOT_METERING_H
#define TURTBOT_METERING_H
#include <math.h>
#include <stdint.h>
#include <stddef.h>
struct camera_meter { double median, p98, saturated, red, blue; unsigned cells, wb_cells; };
static inline double meter_clamp(double x,double low,double high){return fmax(low,fmin(high,x));}
static inline unsigned meter_raw10(const unsigned char *row,unsigned x){
 unsigned group=x/4,slot=x%4;return (row[group*5+slot]<<2)|((row[group*5+4]>>(slot*2))&3);
}
static inline struct camera_meter meter_raw(const unsigned char *raw,unsigned w,unsigned h,unsigned stride){
 struct camera_meter m={.red=1.,.blue=1.};unsigned hist[1024]={0},sat=0;double sr=0,sg=0,sb=0;
 for(unsigned y=0;y+1<h;y+=8)for(unsigned x=0;x+1<w;x+=8){
  unsigned r=meter_raw10(raw+y*stride,x),g1=meter_raw10(raw+y*stride,x+1);
  unsigned g2=meter_raw10(raw+(y+1)*stride,x),b=meter_raw10(raw+(y+1)*stride,x+1),g=(g1+g2)/2;
  hist[g]++;m.cells++;sat+=(r>=1020)+(g1>=1020)+(g2>=1020)+(b>=1020);
  if(r>80&&r<1000&&g>80&&g<900&&b>80&&b<1000){sr+=r-64.;sg+=g-64.;sb+=b-64.;m.wb_cells++;}
 }
 if(!m.cells)return m;
 unsigned n=0,median_target=(m.cells+1)/2,p98_target=(m.cells*98+99)/100;int found=0;
 for(unsigned i=0;i<1024;i++){n+=hist[i];if(!found&&n>=median_target){m.median=fmax(0.,(i-64.)/959.);found=1;}if(n>=p98_target){m.p98=fmax(0.,(i-64.)/959.);break;}}
 m.saturated=sat/(4.*m.cells);
 if(m.wb_cells>=64){m.red=meter_clamp(sg/sr,.5,4.);m.blue=meter_clamp(sg/sb,.5,4.);}
 return m;
}
/* Middle-grey target with a broad-highlight cap; tiny specular lights may clip.
 * Deadband and bounded steps avoid chasing sensor noise or flickering rapidly. */
static inline double meter_exposure_ratio(struct camera_meter m){
 double ratio=fmin(.18/fmax(m.median,.002),.82/fmax(m.p98,.002));
 if(ratio>.90&&ratio<1.10)return 1.;
 return meter_clamp(ratio,.5,2.);
}
#endif
