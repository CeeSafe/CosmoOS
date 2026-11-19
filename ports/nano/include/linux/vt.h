/* The one piece of Linux's <linux/vt.h> nano uses (ports/nano/README.md): it asks
 * VT_GETSTATE whether its output is a Linux virtual console. musl's <sys/vt.h>
 * includes this header, and the BusyBox port's sysroot carries no Linux kernel
 * headers. The values are Linux's user-space ABI. CosmoOS has no virtual
 * consoles: the ioctl fails, and nano takes the terminal for a terminal. */
#ifndef COSMO_PORTS_LINUX_VT_H
#define COSMO_PORTS_LINUX_VT_H

#define VT_GETSTATE 0x5603

struct vt_stat {
    unsigned short v_active;
    unsigned short v_signal;
    unsigned short v_state;
};

#endif
