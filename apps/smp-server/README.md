# SMP Server

Implement a Simple Management Protocol (SMP) server.

## Overview

This sample application implements a Simple Management Protocol (SMP) server.
SMP is a basic transfer encoding for use with the MCUmgr management protocol.
For more information about MCUmgr and SMP, please see the device management documentation.

This sample application supports the following MCUmgr transports by default:

* Shell
* Bluetooth
* UDP

`smp_svr` enables support for the following command groups:

* `fs_mgmt`
* `img_mgmt`
* `os_mgmt`
* `stat_mgmt`
* `shell_mgmt`

## Caveats

* The MCUboot bootloader is required for `img_mgmt` to function
  properly. More information about the Device Firmware Upgrade subsystem and
  MCUboot can be found in the MCUboot documentation.

## Prerequisites

### Use of a tool

To interact remotely with the management subsystem on a device, a tool is required to interact with
it. There are various tools available which are listed on the MCUmgr tools and libraries page
of the Management subsystem documentation which can be used as a client for a Zephyr MCUmgr SMP
server.

### Building a BLE Controller

> **Note:** This section is only relevant for Linux users

If you want to try out Device Firmware Upgrade (DFU) over the air using
Bluetooth Low Energy (BLE) and do not have a built-in or pluggable BLE radio,
you can build one and use it following the instructions in the Bluetooth HCI UART BlueZ documentation.

## Building the sample application

The below steps describe how to build and run the `smp_svr` sample in Zephyr with `MCUboot`
included. The `smp_svr` sample comes in different flavours.

### Bluetooth

To build the bluetooth sample:

```bash
west build -b nrf52dk/nrf52832 samples/subsys/mgmt/mcumgr/smp_svr --sysbuild -- -DEXTRA_CONF_FILE="bt.conf"
```

### Serial

To build the serial sample with file-system and shell management support:

```bash
west build -b frdm_k64f samples/subsys/mgmt/mcumgr/smp_svr --sysbuild -- -DEXTRA_CONF_FILE="serial.conf;fs.conf;shell-mgmt.conf"
```

### USB CDC_ACM

To build the serial sample with USB CDC_ACM backend:

```bash
west build -b nrf52840dk/nrf52840 samples/subsys/mgmt/mcumgr/smp_svr --sysbuild -- -DEXTRA_CONF_FILE="cdc.conf" -DEXTRA_DTC_OVERLAY_FILE="usb.overlay"
```

### Shell

To build the shell sample:

```bash
west build -b frdm_k64f samples/subsys/mgmt/mcumgr/smp_svr --sysbuild -- -DEXTRA_CONF_FILE="shell.conf"
```

### UDP

The UDP transport for SMP supports both IPv4 and IPv6.
In the sample, both IPv4 and IPv6 are enabled, but they can be
enabled and disabled separately.

To build the UDP sample:

```bash
west build -b frdm_k64f samples/subsys/mgmt/mcumgr/smp_svr --sysbuild -- -DEXTRA_CONF_FILE="udp.conf"
```

To build UDP sample with 802154 Subg networking:

```bash
west build -b beagleconnect_freedom samples/subsys/mgmt/mcumgr/smp_svr --sysbuild -- -DEXTRA_CONF_FILE="overlay-udp.conf;802154-subg.conf"
```

## Flashing the sample image

The original application will be built for slot-0, see the flash map API documentation for details on flash
partitioning. Flash both MCUboot and the sample application:

```console
west flash
```

### Sample image: hello world!

The `smp_svr` app is ready to run. Just reset your board and test the app
with your choice of tool's `echo` functionality, which will
send a string to the remote target device and have it echo it back.

## J-Link Virtual MSD Interaction Note

On boards where a J-Link OB is present which has both CDC and MSC (virtual Mass
Storage Device, also known as drag-and-drop) support, the MSD functionality can
prevent mcumgr commands over the CDC UART port from working due to how USB
endpoints are configured in the J-Link firmware (for example on the Nordic
`nrf52840dk`) because of limiting the maximum packet size (most likely to occur
when using image management commands for updating firmware). This issue can be
resolved by disabling MSD functionality on the J-Link device, follow the
instructions on the Nordic Segger MSD documentation to disable MSD support.

## Device Firmware Upgrade (DFU)

Now that the SMP server is running on your board and you are able to communicate with it using a
client, you might want to test what is commonly called "OTA DFU", or Over-The-Air Device Firmware
Upgrade. This works for both BT and UDP.

The general sequence of a DFU process is as follows:

* Build an MCUboot enabled application using sysbuild, see Building the sample application section
* Upload the signed image using an MCUmgr client
* Listing the images on the device using an MCUmgr client
* Mark the uploaded image for testing using an MCUmgr client
* Reset the device remotely using an MCUmgr client
* Confirm the uploaded image using an MCUmgr client (optional)

### Direct image upload and Image mapping to MCUboot slot

Currently MCUmgr supports, for direct upload, 4 target images, of which first two are mapped
into MCUboot primary (slot-0) and secondary (slot-1) respectively.

For clarity, here is DTS label to slot to `<image>` translation table:

| DTS label | Slot   | -n &lt;image&gt; |
| --------- | ------ | ---------------- |
| "image-0" | slot-0 | 1                |
| "image-1" | slot-1 | 0, 1             |
| "image-2" |        | 2                |
| "image-3" |        | 3                |

> **Note:** There is a slot info command that can be used to see information on all slots and get the
> upload `image` ID to use to update that slot, see the MCUmgr SMP group 1 slot info documentation for
> details.

### Upload the signed image

To upload the signed image, refer to the documentation for your chosen tool, select the new
firmware file to upload and begin the upload.

> **Note:** At the beginning of the upload process, the target might start erasing the image slot, taking
> several dozen seconds for some targets.

### List the images

A list of images (slot-0 and slot-1) that are present can now be obtained on the remote target
device using the tool of your choice, which should print the status and hash values of each of
the images present.

### Test the image

In order to instruct MCUboot to swap the images, the image needs to be tested first, making sure it
boots, see the instructions in the tool of your choice. Upon reboot, MCUBoot will swap to the new
image.

> **Note:** Some tools may allow for listing the hash of an image without needing to upload them.
> `imgtool` can also be used to list the image hash, albeit in a C hex-array format, by using
> the `dumpinfo` command on the signed update file, e.g.
>
> ```console
> imgtool dumpinfo smp_svr/zephyr/zephyr.signed.bin
>
> Printing content of signed image: zephyr.signed.bin
>
> #### Image header (offset: 0x0) ############################
> magic:              0x96f3b83d
> ...
> #### TLV area (offset: 0xbfa0) #############################
> magic:     0x6907
> area size: 0x150
>         ---------------------------------------------
>         type: SHA256 (0x10)
>         len:  0x20
>         data: 0x9b 0xa9 0x84 0x48 0xe5 0x4d 0xac 0x40
>               0x62 0x29 0xe2 0x11 0x17 0x96 0x66 0xd9
>               0xae 0x83 0x9a 0x37 0x71 0x00 0xfc 0xe2
>               0xc0 0x30 0x30 0x4f 0xfc 0x40 0x58 0xaa
>         ---------------------------------------------
> ...
> ```
>
> The full SHA256 hash for the above output would be:
> `9ba98448e54dac406229e211179666d9ae839a377100fce2c030304ffc4058aa`

### Reset remotely

The device can be reset remotely to observe (use the console output) how MCUboot swaps the images,
check the documentation in the tool of your choice. Upon reset MCUboot will swap slot-0 and
slot-1.

### Confirm new image

The new image is now loaded into slot-0, but it will be swapped back into slot-1 on the next
reset unless the image is confirmed. Confirm the image using the tool of your choice.

> **Note:** If you try to send the very same image that is already flashed in slot-0 then the procedure
> will not complete successfully since the hash values for both slots will be identical.

## Download files from/upload files to file system

SMP server supports downloading files from/uploading files to the on-device
file system API, this is useful with e.g. FS log backend, when files are stored in
non-volatile memory. Build and flash `smp_svr` using sysbuild and then use the tool of your
choice to download files from the file system. The full path of the file on the device must be
known and used.
