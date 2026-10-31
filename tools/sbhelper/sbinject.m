// Loaded into the Simulator's SpringBoard (DYLD_INSERT_LIBRARIES). On the Darwin
// notification "homescreen.import" it reads $SBTEST_DIR/in.plist and calls
// [[SBApp defaultIconController] importIconState:] -- what SpringBoard's
// SBXXSetIconState handler does for a USB setIconState request -- skipping only the
// entitlement check. The result goes to $SBTEST_DIR/out.txt.
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#import <objc/message.h>
#include <notify.h>

__attribute__((constructor)) static void sbinject_init(void) {
    NSString *dir = NSProcessInfo.processInfo.environment[@"SBTEST_DIR"] ?: @"/tmp";
    static int token;
    notify_register_dispatch("homescreen.import", &token, dispatch_get_main_queue(), ^(int t) {
        NSData *d = [NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:@"in.plist"]];
        id plist = d ? [NSPropertyListSerialization propertyListWithData:d options:0 format:NULL error:NULL] : nil;
        id ctl = ((id (*)(id, SEL))objc_msgSend)(UIApplication.sharedApplication, sel_registerName("defaultIconController"));
        BOOL ok = NO;
        NSString *err = @"";
        @try {
            ok = ((BOOL (*)(id, SEL, id))objc_msgSend)(ctl, sel_registerName("importIconState:"), plist);
        } @catch (NSException *e) {
            err = e.description;
        }
        NSString *res = [NSString stringWithFormat:@"ok=%d input=%@ err=%@\n", ok, NSStringFromClass([plist class]), err];
        [res writeToFile:[dir stringByAppendingPathComponent:@"out.txt"] atomically:YES encoding:NSUTF8StringEncoding error:NULL];
    });
}
