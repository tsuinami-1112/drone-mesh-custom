/* sim_skirt: can a strong FM video carrier 20-32 MHz off the tuned channel pass the
 * firmware's wideband candidate gate through the 40 MHz channel filter's skirt?
 * FM video is generated at 160 MS/s, low-pass filtered (two filter shapes bracket
 * the unknown C5 BW40 response), decimated to 40 MS/s, quantised 3-lane with the
 * firmware's clip loop (3 dB steps while clip > 3 %), then measured with the
 * firmware's own iq_metrics / iq_lag_features (demod.c). Sweep rule as scan_freq:
 * 3 windows, level = min, q / cv2 = median; hit = level>=8 && q>=40 && cv2<=0.5;
 * wb candidate = !hit && min>=8 && max-min<=6 && 0.5<=cv2<=1.5. Then the
 * 8-window pass with wb_classify's rules. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <complex.h>
#include <stdint.h>
#include "demod.h"
#define FS 40.0e6
#define OS 4
#define FSH (FS*OS)
#define N 16384
#define NH (N*OS)
#define PI 3.14159265358979323846
static unsigned g_seed = 777u;
static double urand(void){ g_seed = g_seed*1664525u+1013904223u; return (g_seed>>8)/16777216.0; }
static double nrand(void){ double u1=urand()+1e-12,u2=urand(); return sqrt(-2*log(u1))*cos(2*PI*u2); }
static uint8_t pack(double i,double q){
  long ii=(long)floor(i), qq=(long)floor(q);
  if(ii>7) ii=7;
  if(ii<-8) ii=-8;
  if(qq>7) qq=7;
  if(qq<-8) qq=-8;
  uint8_t b=(uint8_t)(((ii&0xF)<<4)|(qq&0xF));
  g_seed=g_seed*1664525u+1013904223u; return (uint8_t)((b&0xEE)|((g_seed>>20)&0x11));
}
static double complex hi[NH + 1024];
static double complex sig[N];
static uint8_t buf[N];
/* NTSC-like video FM: sync -40 IRE, picture 0..100 IRE, deviation 4 MHz per 100 IRE times dev */
static void gen_fm_hi(double foff, double dev){
  double ls=2542.2*OS, ph=2*PI*urand(), t0=urand()*ls;
  for(int k=0;k<NH+1024;k++){ double s=t0+k; int line=(int)(s/ls); double t=fmod(s,ls)/FSH*1e6, ire;
    if(t<1.5) ire=0; else if(t<6.2) ire=-40; else if(t<10.9) ire=0; else { double a=(t-10.9)/(ls/FSH*1e6-10.9); ire=35+30*sin(2*PI*(3*a+.1*line))+15*((int)(a*7+line)%2); if(ire<0)ire=0; }
    ph+=2*PI*(foff+dev*ire/100*4e6)/FSH; hi[k]=cexp(I*ph); }
}
/* windowed-sinc low-pass at 160 MS/s, applied at the decimated output points */
#define NTMAX 257
static double h[NTMAX]; static int nt;
static void design(double fc, int taps){
  nt=taps; int M=(taps-1)/2; double sum=0;
  for(int k=0;k<taps;k++){ double x=k-M, s=(x==0)?2*fc/FSH:sin(2*PI*fc/FSH*x)/(PI*x); double w=0.54-0.46*cos(2*PI*k/(taps-1)); h[k]=s*w; sum+=h[k]; }
  for(int k=0;k<taps;k++) h[k]/=sum;
}
static double resp_db(double f){ double complex a=0; int M=(nt-1)/2; for(int k=0;k<nt;k++) a+=h[k]*cexp(-I*2*PI*f/FSH*(k-M)); return 20*log10(cabs(a)+1e-12); }
static void filt_decim(void){
  for(int n=0;n<N;n++){ double complex a=0; int base=n*OS+512; for(int k=0;k<nt;k++) a+=h[k]*hi[base-k]; sig[n]=a; }
}
static void quant(double a0,double back_db){ double s=pow(10,-back_db/20.0); for(int k=0;k<N;k++) buf[k]=pack(s*(a0*creal(sig[k])+nrand()), s*(a0*cimag(sig[k])+nrand())); }
static double noise_p;
/* one sweep window with the firmware's gain loop; returns the back-off used */
static int window(double foff,double dev,double a0,int start_back,IqMetrics*m){
  gen_fm_hi(foff,dev); filt_decim();
  int back=start_back;
  for(int att=0;att<30;att++){ quant(a0,back); iq_metrics(buf,N,m); if(m->clip_pct>3.0f && back<60){ back+=3; continue; } break; }
  return back;
}
static float med3(float a,float b,float c){ if((a<=b&&b<=c)||(c<=b&&b<=a))return b; if((b<=a&&a<=c)||(c<=a&&a<=b))return a; return c; }
int main(void){
  demod_init_bits(3);
  { for(int k=0;k<N;k++) sig[k]=0; quant(0,0); IqMetrics m; iq_metrics(buf,N,&m); noise_p=m.p_mean; }
  printf("noise p_mean %.2f (3-lane)\n", noise_p);
  const char* shapes[2]={"soft skirt","sharp skirt"};
  const double offs[]={0,10,15,18,20,22,24,26,28,30,32,35};
  const double snrs[]={20,30,40};
  const double devs[]={1.0,2.0};
  for(int sh=0;sh<2;sh++){
    if(sh==0) design(21.5e6,33); else design(20.5e6,161);
    printf("\n=== filter %s: %.1f dB @20 MHz, %.1f @22, %.1f @25, %.1f @28, %.1f @30, %.1f @35\n", shapes[sh],
      resp_db(20e6),resp_db(22e6),resp_db(25e6),resp_db(28e6),resp_db(30e6),resp_db(35e6));
    for(int dv=0;dv<2;dv++){
      printf("--- video deviation swing %.1f MHz (sync to white)\n", devs[dv]*5.6);
      printf("%4s %4s | %6s %6s %4s %5s | %-4s | %s\n","S/N","off","lvmin","lvmax","q","cv2","gate","8-window pass: duty cls bw r1 r128 r2667 cfo_est(MHz)");
      for(int si=0;si<3;si++){ double a0=sqrt(2*pow(10,snrs[si]/10));
        for(unsigned oi=0;oi<sizeof(offs)/sizeof(offs[0]);oi++){ double foff=offs[oi]*1e6;
          float lv[3],qs[3],cv[3]; int back=0; IqMetrics m;
          for(int w=0;w<3;w++){ back=window(foff,devs[dv],a0,back,&m); lv[w]=back+10*log10(m.p_mean/noise_p); qs[w]=m.q_phase_pct; cv[w]=m.env_cv2; }
          float lmin=fminf(lv[0],fminf(lv[1],lv[2])), lmax=fmaxf(lv[0],fmaxf(lv[1],lv[2])), q=med3(qs[0],qs[1],qs[2]), c=med3(cv[0],cv[1],cv[2]);
          int hit = lmin>=8 && q>=40 && c<=0.5f;
          int wb = !hit && lmin>=8 && lmax-lmin<=6 && c>=0.5f && c<=1.5f;
          printf("%4.0f %4.0f | %6.1f %6.1f %4.0f %5.2f | %-4s |", snrs[si], offs[oi], lmin, lmax, q, c, hit?"HIT":(wb?"WB":"-"));
          if(wb){
            float levels[8],r1=0,r128=0,r2667=0,cfo=0,lmaxp=-1e9; IqLagFeatures lf[8]; IqMetrics mm[8];
            for(int w=0;w<8;w++){ gen_fm_hi(foff,devs[dv]); filt_decim(); quant(a0,back); iq_metrics(buf,N,&mm[w]); iq_lag_features(buf,N,&lf[w]); levels[w]=back+10*log10(mm[w].p_mean/noise_p); if(levels[w]>lmaxp)lmaxp=levels[w]; }
            int on=0; float lsum=0;
            for(int w=0;w<8;w++){ if(levels[w]<lmaxp-6) continue; on++; lsum+=levels[w]; r1+=lf[w].r1; r128+=lf[w].r128; r2667+=lf[w].r2667; cfo+=mm[w].cfo_khz; }
            r1/=on; r128/=on; r2667/=on; cfo/=on; float lev=lsum/on;
            const char* cls = (r2667>=0.03f && r128<0.05f) ? "lte" : (r128>=0.10f ? "dot11" : "wb");
            float r1s=r1*(1+powf(10,-lev/10)); if(r1s>1)r1s=1; int bw = r1s>=0.78f?10:(r1s>=0.52f?20:(r1s>=0.30f?30:40));
            printf(" duty %3d %-5s %2d MHz r1 %.2f r128 %.3f r2667 %.3f cfo %+.1f", 100*on/8, cls, bw, r1, r128, r2667, cfo/1000);
          }
          printf("\n");
        }
      }
    }
  }
  return 0;
}
