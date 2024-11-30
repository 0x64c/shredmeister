# SHREDMEISTER
# 2024 Hanyu Lin
# 
# This program will erase drives. You have been warned.
# To test erasing functionality, uncomment lines 73 and 76, comment out lines 74 and 77.
# Please report bugs/crashes/edge conditions. Some drives, USB enclosures or card readers may not work properly.
# 
# Required packages: (most will be there by default)
# jq smartmontools findutils util-linux-libs grep python-pysimplegui python-humanize
# 
# Required packages:
# pacman -Syu jq smartmontools grep python-humanize
# yay -S python-pysimplegui
# 
# to run this script as not super user:
# chmod u+s /usr/sbin/hexdump /usr/sbin/smartctl /usr/sbin/blkdiscard /usr/sbin/shred
#

import PySimpleGUI as sg
import os
import json
import subprocess
import signal
import humanize
import time
import threading

smart_data_dict= dict()
unmounted_drives = dict()
subproc_list = list()
timer_list_short = list()
timer_list_extended = list()
short_tested_drives = set()
long_tested_drives = set()
erased_drives = set()

def get_serials_from_drive_paths(drive_paths):
    drives=dict()
    for i in drive_paths:
        block=i.split('/')[-1]
        try:
            myfile=open(f'/sys/block/{block}/device/serial','r')
            serial=myfile.readline().rstrip()
            myfile.close()
            drives[serial]=i
        except:
            pass
    return drives

def get_mounted_drives():
    return os.popen(r"mount|grep --only-matching -e '^/dev/nvme[0-9]n[0-9]\|^/dev/sd[a-z]'").read().splitlines()

def get_drives():
    drive_paths=os.popen(r"find /dev -type b -regex '/dev/sd[a-x]+\|/dev/nvme[0-9]n[0-9]'").read().splitlines()
    return get_serials_from_drive_paths(drive_paths)

def remove_mounted_drives(all_drives, mounted_drives):
    for key,value in all_drives.copy().items():
        if value in mounted_drives:
            all_drives.pop(key)

def get_smart(drive_path):
    if drive_path != None:
        return os.popen(r"smartctl -aj " + drive_path).read()

def popup_smart_data(drive_path):
    if drive_path != None:
        sg.popup_scrolled(os.popen(r"smartctl -a " + drive_path).read(),title=drive_path,font="Monospace 8")
    
def erase_drive(drive_path,device_type):
    if drive_path != None:
        if device_type == 'NVMe':
            #return subprocess.Popen(['blkdiscard','-q','-s','-f',drive_path])
            return subprocess.Popen(['sleep','5'])
        else:
            #return subprocess.Popen(['shred','-n','0','-z',drive_path])
            return subprocess.Popen(['sleep','5'])

def hexdump(drive_path):
    if drive_path != None:
        sg.popup_scrolled(os.popen(r"hexdump -C -n17408 " + drive_path).read(),title=f'{drive_path} LBA Check',font="Monospace 8")

def mark_short_tested(drive_path):
    short_tested_drives.add(drive_path)
    for item in timer_list_short:
        if drive_path in item:
            timer_list_short.remove(item)
    
def mark_long_tested(drive_path):
    long_tested_drives.add(drive_path)
    for item in timer_list_extended:
        if drive_path in item:
            timer_list_extended.remove(item)
    
def short_test(serial,drive_path):
    if drive_path != None:
        proc_status=subprocess.Popen(["smartctl","-X","-q","silent","-t","short",drive_path])
        t = threading.Timer(5,mark_short_tested,args=(serial,))
        t.start()
        return t

def long_test(serial,drive_path):
    if drive_path != None:
        proc_status=subprocess.Popen(["smartctl","-X","-q","silent","-t","long",drive_path])
        t = threading.Timer(2,mark_long_tested,args=(serial,))
        t.start()
        return t

def is_in_sublist(thing,biglist):
    for list_ in biglist:
        if thing in list_:
            return True
    return False
   
def refresh(serial,data):
    smart_data_dict[serial]=json.loads(get_smart(unmounted_drives[serial]))
    device_model=data.get("model_name")
    device_protocol=data.get("device", {}).get("protocol")
    device_serial=data.get("serial_number")
    drive_bytes=data.get("user_capacity",{}).get("bytes")
    drive_capacity=humanize.naturalsize(int( 0 if drive_bytes is None else drive_bytes))
    rpm=data.get("rotation_rate")
    table_data,new_row_colors=make_table_data(serial,data)
    erasing=is_in_sublist(device_serial,subproc_list)
    erased="..." if erasing else "✔" if device_serial in erased_drives else "❌"
    if erasing:
        window[f'-Erase-'].update(disabled=True)
    else:
        window[f'-Erase-'].update(disabled=False)
    short_tested="..." if is_in_sublist(device_serial,timer_list_short) else "✔" if device_serial in short_tested_drives else "❌"
    long_tested="..." if is_in_sublist(device_serial,timer_list_extended) else "✔" if device_serial in long_tested_drives else "❌"
    window[f'{device_serial} status'].update(value=f'Erased: {erased} Short: {short_tested} Extended: {long_tested}')
    if device_protocol == 'NVMe':
        window[f'{device_serial} model'].update(value=f'{device_model} {device_protocol} {drive_capacity}')
        window[f'-Short-'].update(disabled=True)
        window[f'-Long-'].update(disabled=True)
    else:
        window[f'{device_serial} model'].update(value=f'{device_model} {device_protocol} {drive_capacity} {rpm} RPM')
        window[f'-Short-'].update(disabled=False)
        window[f'-Long-'].update(disabled=False)
    window[f'{device_serial} sn'].update(value=f'S/N: {device_serial}')
    window[f'{device_serial} table'].update(values=table_data[:][:],row_colors=new_row_colors)
    window.refresh()

def make_table_data(drive,data):
    smart_passed=data.get("smart_status", {}).get("passed")
    device_protocol=data.get("device", {}).get("protocol")
    #drive_bytes=data.get("user_capacity",{}).get("bytes")
    #drive_capacity=humanize.naturalsize(int( 0 if drive_bytes is None else drive_bytes))
    my_row_colors = []
    if(device_protocol == 'NVMe'):
        table_data=[
            ["Available Spare", data.get("nvme_smart_health_information_log", {}).get("available_spare") ],
            ["Power Cycles", data.get("nvme_smart_health_information_log", {}).get("power_cycles") ],
            ["Hours", data.get("nvme_smart_health_information_log", {}).get("power_on_hours") ],
            ["Unsafe Shutdowns", data.get("nvme_smart_health_information_log", {}).get("unsafe_shutdowns") ],
            ["Data Read", data.get("nvme_smart_health_information_log", {}).get("data_units_read") ],
            ["Data Written", data.get("nvme_smart_health_information_log", {}).get("data_units_written") ],
            ["Media Errors", data.get("nvme_smart_health_information_log", {}).get("media_errors") ]
        ]
        if(table_data[0][1]<80):
            my_row_colors.append([0,"black","yellow"])
        elif(table_data[0][1]<50):
            my_row_colors.append([0,"black","red"])
        else:
            my_row_colors.append([0,"black","green"])
    else:
        table_data=[
            ["Smart Passed", data.get("ata_smart_data",{}).get("self_test", {}).get("status",{}).get("passed") ],
            ["Smart Status", data.get("ata_smart_data",{}).get("self_test", {}).get("status",{}).get("string") ],
            ["Power On Time", data.get("power_on_time") ],
            ["Power Cycle Count", data.get("power_cycle_count") ],
        ]
        if(table_data[0][1]==True):
            my_row_colors.append([0,"black","green"])
        else:
            my_row_colors.append([0,"black","red"]) 
        for tup in data.get("ata_smart_attributes",{}).get("table") or []:
            if(tup.get("id",{}) == 5):
                val=tup.get("raw",{}).get("value")
                table_data.append(["RAS",val])
                index=len(table_data)-1
                if(val>0):
                    my_row_colors.append([index,"black","red"])
                else:
                    my_row_colors.append([index,"black","green"])
            elif(tup.get("id",{}) == 197):
                val=tup.get("raw",{}).get("value")
                table_data.append(["Pending",val])
                index=len(table_data)-1
                if(val>0):
                    my_row_colors.append([index,"black","red"])
                else:
                    my_row_colors.append([index,"black","green"])
            elif(tup.get("id",{}) == 191):
                val=tup.get("raw",{}).get("value")
                table_data.append(["GSENSE",val])
                index=len(table_data)-1
                if(val>0):
                    my_row_colors.append([index,"black","red"])
                else:
                    my_row_colors.append([index,"black","green"])
            elif(tup.get("id",{}) == 191):
                val=tup.get("raw",{}).get("value")
                table_data.append(["GSENSE",val])
                index=len(table_data)-1
                if(val>0):
                    my_row_colors.append([index,"black","red"])
                else:
                    my_row_colors.append([index,"black","green"])
    return table_data,my_row_colors

def make_table(drive,data):
    table_header=["Attribute", "Value"]
    table_data, my_row_colors = make_table_data(drive,data)
    return sg.Table(
        values=table_data[:][:],
        headings=table_header,
        justification='left',
        row_colors=my_row_colors,
        key=f'{drive} table'
    )
        
def new_tab(data):
    device_model=data.get("model_name")
    device_protocol=data.get("device", {}).get("protocol")
    device_serial=data.get("serial_number")
    drive_bytes=data.get("user_capacity",{}).get("bytes")
    drive_capacity=humanize.naturalsize(int( 0 if drive_bytes is None else drive_bytes))
    erased="✔" if device_serial in erased_drives else "❌"
    short_tested="✔" if device_serial in short_tested_drives else "❌"
    long_tested="✔" if device_serial in long_tested_drives else "❌"
    if(device_protocol == 'NVMe'):
        return sg.Tab(
            f'{device_serial}',
            [
                [
                    sg.Text(f'{device_model} {device_protocol} {drive_capacity}',key=f'{device_serial} model'),
                ],
                [
                    sg.Text(f'S/N: {device_serial}',key=f'{device_serial} sn'),
                ],
                [
                    sg.Text(f'Erased: {erased}',key=f'{device_serial} status'),
                ],
                [
                    make_table(device_serial,data)
                ]
            ],
            key=f'{device_serial}'
        )
    else:
        rpm=data.get("rotation_rate")
        return sg.Tab(
            f'{device_serial}',
            [
                [
                    sg.Text(f'{device_model} {device_protocol} {drive_capacity} {rpm} RPM' ,key=f'{device_serial} model'),
                ],
                [
                    sg.Text(f'S/N: {device_serial}',key=f'{device_serial} sn'),
                ],
                [
                    sg.Text(f'Erased: {erased} Short: {short_tested} Extended: {long_tested}',key=f'{device_serial} status'),
                ],
                [
                    make_table(device_serial,data)
                ]
            ],
            key=f'{device_serial}'
        )

def scan():
    global unmounted_drives
    new_mounted_drives=get_mounted_drives()
    unmounted_drives=get_drives()
    remove_mounted_drives(unmounted_drives,new_mounted_drives)
    if len(unmounted_drives) > 0:
        for serial,path in unmounted_drives.items():
            smart_data_dict[serial]=json.loads(get_smart(path))

def rescan():
    global unmounted_drives
    new_mounted_drives=get_mounted_drives()
    new_all_drives=get_drives()
    remove_mounted_drives(new_all_drives,new_mounted_drives)
    new_drives=dict()
    for key,value in new_all_drives.items():
        if key in unmounted_drives.keys():
            unmounted_drives[key]=value
        else:
            json_data=json.loads(get_smart(value))
            smart_data_dict[key]=json_data
            window['Tabgroup'].add_tab(new_tab(smart_data_dict[key]))
            pass
    for key,value in unmounted_drives.copy().items():
        if key not in new_all_drives.keys():
            unmounted_drives.pop(key)
            window[f'{key}'].update(visible=False)
    window.refresh()

scan()

tabgroup = sg.TabGroup(
    [[new_tab(data) for data in smart_data_dict.values()]],
    key='Tabgroup',
    enable_events = True
)

layout = [
    [sg.Column(
        [
            [tabgroup],
            [
                sg.Button('Short Test',key="-Short-"),
                sg.Button('Long Test',key="-Long-"),
                sg.Button('Erase',key="-Erase-"),
                sg.Button('SMART',key="-SMART-"),
                sg.Button('HEXDUMP',key="-HEX-"),
                sg.Button('Refresh',key="-Refresh-"),
            ]
        ],
        #scrollable=True,
        #vertical_scroll_only=False,
        size_subsample_height=1,
        size_subsample_width=1,
        key='Column'
    )],
]

window = sg.Window('Shredmeister', layout, finalize=True)

def sigchld_handler(signum, frame):
    global window
    window.write_event_value('-RefreshPage-',1)

signal.signal(signal.SIGCHLD, sigchld_handler)

time_last_polled=0
window.write_event_value('-RefreshPage-',1)

while True:
    event,values=window.read()
    current_time=time.time()
    if current_time - time_last_polled > 1:
        time_last_polled=current_time
        for item in subproc_list:
            exitcode=item[1].poll()
            if exitcode != None:
                if exitcode == 0:
                    erased_drives.add(item[0])
                item[1].terminate()
                subproc_list.remove(item)
            
    if event == sg.WIN_CLOSED:
        break
    elif event == "-Erase-":
        drive=values.get("Tabgroup")
        if(drive != None):
            protocol=smart_data_dict[drive].get('device',{}).get('protocol')
            subproc_list.append([drive,erase_drive(str(unmounted_drives[drive]),protocol)])
            refresh(drive,smart_data_dict[drive])
    elif event == "-Long-":
        drive=values.get("Tabgroup")
        if(drive != None):
            t=long_test(drive,str(unmounted_drives[drive]))
            timer_list_extended.append([drive,t])
    elif event == "-Short-":
        drive=values.get("Tabgroup")
        if(drive != None):
            t=short_test(drive,str(unmounted_drives[drive]))
            timer_list_short.append([drive,t])
    elif event == "-SMART-":
        drive=values.get("Tabgroup")
        if(drive != None):
            popup_smart_data(str(unmounted_drives[drive]))
    elif event == "-Refresh-":
        rescan()
        drive=values.get("Tabgroup")
        if(drive != None):
            refresh(drive,smart_data_dict[drive])
    elif event == "-RefreshPage-":
        drive=values.get("Tabgroup")
        if(drive != None):
            refresh(drive,smart_data_dict[drive])
    elif event == "-HEX-":
        drive=values.get("Tabgroup")
        if(drive != None):
            hexdump(str(unmounted_drives[drive]))
    elif event == "Tabgroup":
        drive=values.get("Tabgroup")
        if(drive != None):
            refresh(drive,smart_data_dict[drive])

window.close()

