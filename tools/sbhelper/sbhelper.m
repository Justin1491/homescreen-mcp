// Runs inside an iOS Simulator and talks to SpringBoard the way the on-device
// springboardservicesrelay does for USB getIconState / setIconState requests.
//   sbhelper set <file.plist>   send the plist as the new icon state
//   sbhelper get [out.plist]    fetch SpringBoard's icon state
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <mach/mach.h>

typedef mach_port_t (*PortFn)(void);
typedef kern_return_t (*SetFn)(mach_port_t, const void *, mach_msg_type_number_t);
typedef kern_return_t (*GetFn)(mach_port_t, vm_address_t *, mach_msg_type_number_t *);

int main(int argc, char **argv) {
    @autoreleasepool {
        void *h = dlopen("/System/Library/PrivateFrameworks/SpringBoardServices.framework/SpringBoardServices", RTLD_NOW);
        if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
        PortFn port = (PortFn)dlsym(h, "SBSSpringBoardServerPort");
        if (!port) { fprintf(stderr, "no SBSSpringBoardServerPort\n"); return 1; }
        mach_port_t p = port();
        if (argc >= 3 && strcmp(argv[1], "set") == 0) {
            SetFn set = (SetFn)dlsym(h, "SBSetIconState");
            NSData *d = [NSData dataWithContentsOfFile:@(argv[2])];
            if (!set || !d) { fprintf(stderr, "missing SBSetIconState or file\n"); return 1; }
            id plist = [NSPropertyListSerialization propertyListWithData:d options:0 format:NULL error:NULL];
            NSData *bin = [NSPropertyListSerialization dataWithPropertyList:plist format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
            kern_return_t kr = set(p, bin.bytes, (mach_msg_type_number_t)bin.length);
            printf("set kr=%d (%s)\n", kr, NSStringFromClass([plist class]).UTF8String);
            return kr != KERN_SUCCESS;
        }
        if (argc >= 2 && strcmp(argv[1], "get") == 0) {
            GetFn get = (GetFn)dlsym(h, "SBGetIconState");
            vm_address_t buf = 0; mach_msg_type_number_t len = 0;
            kern_return_t kr = get ? get(p, &buf, &len) : -1;
            printf("get kr=%d len=%u\n", kr, len);
            if (kr == KERN_SUCCESS && argc >= 3) {
                [[NSData dataWithBytes:(void *)buf length:len] writeToFile:@(argv[2]) atomically:YES];
            }
            return kr != KERN_SUCCESS;
        }
        fprintf(stderr, "usage: sbhelper set <file.plist> | get [out.plist]\n");
        return 2;
    }
}
