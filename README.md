# shredmeister
Python application for bulk testing and erasing of storage devices.

## Required packages
python-pysimplegui
python-humanize
smartmontools
jq

## Instructions
### Installation
pacman -Syu jq smartmontools grep python-humanize
yay -S python-pysimplegui

### Run as non-super user
chmod u+s /usr/sbin/hexdump /usr/sbin/smartctl /usr/sbin/blkdiscard /usr/sbin/shred
