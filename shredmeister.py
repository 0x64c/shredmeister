# SHREDMEISTER
# 2024 Hanyu Lin
# 
# This program will erase drives. You have been warned.
# Please report bugs/crashes/edge conditions. Some drives, USB enclosures or card readers may not work properly.
# 
# Required packages: (most will be there by default)
# jq smartmontools findutils util-linux-libs grep python-pysimplegui python-humanize
# 
# Required packages:
# pacman -Syu jq smartmontools grep python-humanize python-paramiko
# yay -S python-pysimplegui
# 
# to run this script as not super user:
# chmod u+s /usr/sbin/hexdump /usr/sbin/smartctl /usr/sbin/blkdiscard /usr/sbin/shred
#
# todo:
# more debugging, look for edge cases
# add ability to modify smart attributes and how they are displayed (perhaps external json file)
# add ability to export or load list of processed drives

import PySimpleGUI as sg
import os
import json
import subprocess
import signal
import humanize
import time
import threading
import argparse

smart_data_dict= dict()
all_drives=dict()
subproc_list = list()
timer_list_short = list()
timer_list_extended = list()

QUIT=False

#returns dictionary of drives, format is "{serial}"->"{path}"
def get_serials_from_drive_paths(drive_paths):
    drives=dict()
    for i in drive_paths:
        #faster method but doesn't work with all drive types
        try:
            block=i.split('/')[-1]
            serial=subprocess.check_output(['cat',f'/sys/block/{block}/device/serial']).rstrip().decode("utf-8")
        except subprocess.CalledProcessError as e:
            print(f'Unable to get serial for device {i} from virtual filesystem. Proceeding with smartctl method.')
        else:
            drives[serial]=i
            continue
        #fall back to reading json data
        try:
            data=json.loads(get_smart(i))
            serial=data['serial_number']
            #do not add drive if we can't get a serial
            if serial is None:
                raise TypeError
        except TypeError as e:
            print(f'Unable to get serial for device {i} from smartctl. Not populating.')
        else:
            #print(f'Found serial {serial} for drive {i} through smartctl.')
            drives[serial]=i
    return drives

#returns list of mounted drives as a dict "{serial}"->"{path}"
def get_mounted_drives():
    try:
        mount=subprocess.Popen(['mount'],stdout=subprocess.PIPE)
        grep=subprocess.Popen(['grep','--only-matching','-e',r'^/dev/nvme[0-9]n[0-9]\|^/dev/sd[a-z]'],stdin=mount.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        mount.stdout.close()
        output,err=grep.communicate()
        drive_paths=output.decode("utf-8").splitlines()
    except subprocess.CalledProcessError as e:
        print('Subprocess for get_mounted_drives() failed:')
        print(e)
        pass
    return get_serials_from_drive_paths(drive_paths)

#returns list of connected drives as a dict "{serial}"->"{path}"
def get_drives():
    try:
        drive_paths=''
        output=subprocess.check_output(['find','/dev','-type','b','-regex',r'/dev/sd[a-x]+\|/dev/nvme[0-9]n[0-9]']).decode('utf-8').splitlines()
    except subprocess.CalledProcessError as e:
        print('Subprocess for get_drives() failed:')
        print(e)
    else:
        drive_paths=output
    return get_serials_from_drive_paths(drive_paths)


#retrieve smart data as JSON
def get_smart(drive_path):
    try:
        output=subprocess.run(['smartctl','-aj',drive_path],stdout=subprocess.PIPE)
        data=output.stdout
        #check if bit 1 or 2 of the return code is set (command line did not parse or drive not found)
        if output.returncode & 3 :
            raise Exception()
    #too tired to do this properly
    except Exception as e:
        print(f'Subprocess for get_smart({drive_path}) failed:')
        print(e)
    else:
        return output.stdout

#display popup with smartctl printout
def popup_smart_data(drive_path):
    try:
        output=subprocess.run(['smartctl','-a',drive_path],stdout=subprocess.PIPE)
    except:
        pass
    else:
        sg.popup_scrolled(output.stdout.decode('utf-8'),title=drive_path,font="Monospace 8")

#initiate drive erasure; method dependent on drive type
#returns handle to subprocess, which we can poll later to check for exit code to know when it's done
def erase_drive(drive_path,device_type):
    if drive_path != None:
        if device_type == 'NVMe':
            return subprocess.Popen(['blkdiscard','-q','-s','-f',drive_path])
            #return subprocess.Popen(['sleep','5'])
        else:
            return subprocess.Popen(['shred','-n','0','-z',drive_path])
            #return subprocess.Popen(['sleep','5'])

#display popup with hexdump printout of first few LBA of drive
def hexdump(drive_path):
    try:
        output=subprocess.run(['hexdump','-C','-n17408',drive_path],stdout=subprocess.PIPE)
    except:
        pass
    else:
        sg.popup_scrolled(output.stdout.decode('utf-8'),title=f'{drive_path} LBA Check',font="Monospace 8")

#callback functions for marking drives as tested after timer subprocess completion
def mark_short_tested(serial):
    all_drives[serial].short_tested=True
    for item in timer_list_short:
        if serial in item:
            timer_list_short.remove(item)
    window.write_event_value('-RefreshPage-',1)
def mark_long_tested(serial):
    all_drives[serial].long_tested=True
    for item in timer_list_extended:
        if serial in item:
            timer_list_extended.remove(item)
    window.write_event_value('-RefreshPage-',1)

#initiate conveyance tests; runs a timer that expires at the estimated completion time
#after timer expires, callback functions are run to mark drives as tested
def short_test(serial,drive_path,eta):
    if drive_path != None:
        proc_status=subprocess.Popen(["smartctl","-q","silent","-t","short",drive_path])
        t = threading.Timer(eta,mark_short_tested,args=(serial,))
        t.start()
        return t
def long_test(serial,drive_path,eta):
    if drive_path != None:
        proc_status=subprocess.Popen(["smartctl","-q","silent","-t","long",drive_path])
        t = threading.Timer(eta,mark_long_tested,args=(serial,))
        t.start()
        return t

#helper function to check if something exists in a sublist of a list
def is_in_sublist(thing,biglist):
    for list_ in biglist:
        if thing in list_:
            return True
    return False

#refresh the displayed data for the tab of the specified drive, given its smart data
def refresh(serial,use_stale_data=False):
    print(f'refreshing {serial}')
    if serial == 'main_tab':
        window[f'-Erase-'].update(disabled=True)
        window[f'-Short-'].update(disabled=True)
        window[f'-Long-'].update(disabled=True)
        window[f'-SMART-'].update(disabled=True)
        window[f'-HEX-'].update(disabled=True)
        window[f'-main-tab-table-'].update(values=[(
            [serial,drive.path,drive.short_tested,drive.long_tested,drive.erased]) for serial,drive in all_drives.items()
        ])
        #printout='Drives:\n'
        #window[f'-main-tab-text-'].update(value=f'{printout}')
    #hide tab and remove any running timers
    elif all_drives[serial].removed:
        window[f'{serial}'].update(visible=False)
        #I don't like how this is iterated, but should be fine since there should be only one timer per type of test per drive...
        for i in range(len(timer_list_short)):
            if timer_list_short[i][0] == serial:
                timer_list_short[i][1].cancel()
                del timer_list_short[i]
        for i in range(len(timer_list_short)):
            if timer_list_short[i][0] == serial:
                timer_list_short[i][1].cancel()
                del timer_list_short[i]
                
    else:
        window[f'{serial}'].update(visible=True)
        window[f'-SMART-'].update(disabled=False)
        window[f'-HEX-'].update(disabled=False)
        if use_stale_data:
            data=smart_data_dict[serial]
        else:
            data=smart_data_dict[serial]=json.loads(get_smart(all_drives[serial].path))
        device_model=data['model_name']
        device_protocol=data['device']['protocol']
        drive_bytes=data['user_capacity']['bytes']
        drive_capacity=humanize.naturalsize(int( 0 if drive_bytes is None else drive_bytes))
        table_data,new_row_colors=make_table_data(serial,data)
        erasing=is_in_sublist(serial,subproc_list)
        erased="..." if erasing else "✔" if all_drives[serial].erased else "❌"
        if erasing or all_drives[serial].mounted:
            window[f'-Erase-'].update(disabled=True)
        else:
            window[f'-Erase-'].update(disabled=False)
        short_tested="..." if is_in_sublist(serial,timer_list_short) else "✔" if all_drives[serial].short_tested else "❌"
        long_tested="..." if is_in_sublist(serial,timer_list_extended) else "✔" if all_drives[serial].long_tested else "❌"
        window[f'{serial} status'].update(value=f'Erased: {erased} Short: {short_tested} Extended: {long_tested}')
        if device_protocol == 'NVMe':
            window[f'{serial} model'].update(value=f'{device_model} {device_protocol} {drive_capacity}')
            window[f'-Short-'].update(disabled=True)
            window[f'-Long-'].update(disabled=True)
        else:
            rpm=data['rotation_rate']
            window[f'{serial} model'].update(value=f'{device_model} {device_protocol} {drive_capacity} {rpm} RPM')
            window[f'-Short-'].update(disabled=False)
            window[f'-Long-'].update(disabled=False)
        window[f'{serial} sn'].update(value=f'S/N: {serial}')
        window[f'{serial} table'].update(values=table_data[:][:],row_colors=new_row_colors)
    window.refresh()

#populate data table for specified drive, given its smart data
def make_table_data(drive,data):
    try:
        smart_passed=''
        try:
            smart_passed=data['smart_status']['passed']
        except KeyError as e:
            smart_passed='n/a'
        device_protocol=data['device']['protocol']
        my_row_colors = []
        if(device_protocol == 'NVMe'):
            table_data=[
                ["SMART Passed", smart_passed ],
                ["Available Spare", data['nvme_smart_health_information_log']['available_spare'] ],
                ["Power Cycles", data['nvme_smart_health_information_log']['power_cycles'] ],
                ["Hours", humanize.naturalsize(data['nvme_smart_health_information_log']['power_on_hours'])[:-1]+' hours' ],
                ["Unsafe Shutdowns", data['nvme_smart_health_information_log']['unsafe_shutdowns'] ],
                ["Data Read", humanize.naturalsize(data['nvme_smart_health_information_log']['data_units_read']*512000)],
                ["Data Written", humanize.naturalsize(data['nvme_smart_health_information_log']['data_units_written']*512000) ],
                ["Media Errors", data['nvme_smart_health_information_log']['media_errors'] ]
            ]
            
            if(table_data[0][1]==True):
                my_row_colors.append([0,"black","green"])
            else:
                my_row_colors.append([0,"black","red"])
            
            if(table_data[1][1]<80):
                my_row_colors.append([1,"black","yellow"])
            elif(table_data[1][1]<50):
                my_row_colors.append([1,"black","red"])
            else:
                my_row_colors.append([1,"black","green"])
        else:
            power_on_hours=None
            try:
                my_hours=data['power_on_time']['hours']
            except KeyError as e:
                try:
                    my_hours=data['power_on_time']['seconds']
                except KeyError as e:
                    pass
                else:
                    power_on_hours=int(my_hours/3600)
            else:
                power_on_hours=int(my_hours)

            ata_smart_passed=None
            try:
                ata_smart_passed=data['ata_smart_data']['self_test']['status']['passed']
            except KeyError as e:
                ata_smart_passed='N/A'

            table_data=[
                ["Smart Passed", ata_smart_passed ],
                ["Smart Status", data['ata_smart_data']['self_test']['status']['string'] ],
                ["Power On Time", humanize.naturalsize(power_on_hours)[:-1]+' hours' ],
                ["Power Cycle Count", data['power_cycle_count'] ],
            ]
            #set the colour of certain rows depending on value, to highlight good and bad attributes
            if(table_data[0][1]==True):
                my_row_colors.append([0,"black","green"])
            else:
                my_row_colors.append([0,"black","red"])
            
            for row in data['ata_smart_attributes']['table']:
                match(row['id']):
                    case 5:
                        val=row['raw']['value']
                        table_data.append(["RAS",val])
                        index=len(table_data)-1
                        if(val>0):
                            my_row_colors.append([index,"black","red"])
                        else:
                            my_row_colors.append([index,"black","green"])
                    case 197:
                        val=row['raw']['value']
                        table_data.append(["Pending",val])
                        index=len(table_data)-1
                        if(val>0):
                            my_row_colors.append([index,"black","red"])
                        else:
                            my_row_colors.append([index,"black","green"])
                    case 191:
                        val=row['raw']['value']
                        table_data.append(["GSENSE",val])
                        index=len(table_data)-1
                        if(val>0):
                            my_row_colors.append([index,"black","red"])
                        else:
                            my_row_colors.append([index,"black","green"])
                    case 241:
                        val=row['raw']['value']
                        table_data.append(["Data Written",humanize.naturalsize(val*512)])
                    case 242:
                        val=row['raw']['value']
                        table_data.append(["Data Read",humanize.naturalsize(val*512)])
                    case 194:
                        val=row['flags']['value']
                        table_data.append(["Temperature",f'{val}°C'])
                    case 12:
                        val=row['flags']['value']
                        table_data.append(["Power Cycles",f'{val}'])
        return table_data,my_row_colors
    except KeyError as e:
        print(f'KeyError in make_data_table() for {drive}: {e}')
        return [],[]

#make table for main tab to display list of all drives and their status
def main_tab_table():
    table_header=["S/N","Path","Short","Long","Erased"]
    table_data=[
        ([serial,drive.path,drive.short_tested,drive.long_tested,drive.erased]) for serial,drive in all_drives.items()
    ]
    return sg.Table(
        values=table_data[:][:],
        headings=table_header,
        justification='left',
        key=f'-main-tab-table-'
    )

#create data table for given drive
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
    
#default tab; we need at least one tab for the tabgroup to work properly
def main_tab():
    return sg.Tab(
        f'Main Tab',
        [
            [
                #sg.Text(f'Main Tab',key='-main-tab-text-'),
                main_tab_table(),
            ]
        ],
        key=f'main_tab'
    )

#create new tab for a drive  
def new_tab(serial):
    data=smart_data_dict[serial]=json.loads(get_smart(all_drives[serial].path))
    device_model=data['model_name']
    device_protocol=data['device']['protocol']
    drive_bytes=data['user_capacity']['bytes']
    drive_capacity=humanize.naturalsize(int( 0 if drive_bytes is None else drive_bytes))
    erased="✔" if all_drives[serial].erased else "❌"
    short_tested="✔" if all_drives[serial].short_tested else "❌"
    long_tested="✔" if all_drives[serial].long_tested else "❌"
    if(device_protocol == 'NVMe'):
        return sg.Tab(
            f'{serial}',
            [
                [
                    sg.Text(f'{device_model} {device_protocol} {drive_capacity}',key=f'{serial} model'),
                ],
                [
                    sg.Text(f'S/N: {serial}',key=f'{serial} sn'),
                ],
                [
                    sg.Text(f'Erased: {erased}',key=f'{serial} status'),
                ],
                [
                    make_table(serial,data)
                ]
            ],
            key=f'{serial}'
        )
    else:
        rpm=data['rotation_rate']
        return sg.Tab(
            f'{serial}',
            [
                [
                    sg.Text(f'{device_model} {device_protocol} {drive_capacity} {rpm} RPM' ,key=f'{serial} model'),
                ],
                [
                    sg.Text(f'S/N: {serial}',key=f'{serial} sn'),
                ],
                [
                    sg.Text(f'Erased: {erased} Short: {short_tested} Extended: {long_tested}',key=f'{serial} status'),
                ],
                [
                    make_table(serial,data)
                ]
            ],
            key=f'{serial}'
        )

#detects connected storage drives, makes an object for each, adds them to dictionary
def scan():
    global all_drives
    mounted_drives=get_mounted_drives()
    drives=get_drives()
    if(len(drives)>0):
        for serial,path in drives.items():
            mounted=False
            if serial in mounted_drives:
                mounted = True
            all_drives[f'{serial}']=Drive(serial,path,mounted)
            #all_drives.append(serial,Drive(serial,path,mounted))
            smart_data_dict[serial]=json.loads(get_smart(path))

#object class to keep record of drives that have been connected
class Drive:
    def __init__(self,serial,path,mounted):
        self.serial=serial
        self.path=path
        self.mounted=mounted
        self.removed=False
        self.erased=False
        self.short_tested=False
        self.long_tested=False
    def __hash__(self):
        return hash(self.serial)
    def __str__(self):
        if self.removed:
            return f"S/N {self.serial}, Not connected"
        if self.mounted:
            return f"S/N {self.serial}, {self.path}, Mounted"
        return f"S/N {self.serial}, {self.path}, Unmounted"
    def remove(self):
        self.path=None
        self.mounted=False
        self.removed=True
    def update(self,path,mounted):
        self.path=path
        self.mounted=mounted
        self.removed=False

#refresh tabs, add new tabs for new drives, hide tabs for missing drives, etc
def rescan():
    print('rescanning drives')
    global all_drives
    mounted_drives=get_mounted_drives()
    new_all_drives=get_drives()
    #repopulate SMART data from drives that are present
    #for drive in new_all_drives.values():
        #if drive.removed == False:
    #    smart_data_dict[serial]=json.loads(get_smart(path))
    #iterate over old list of drives
    for serial,drive in all_drives.items():
        #mark drive as removed if not in new list of all drives
        if serial not in new_all_drives.keys():
            drive.remove()
        else:
        #update status of already listed drive
            mounted=False
            if serial in mounted_drives:
                mounted=True
            drive.update(new_all_drives[serial],mounted)
        #quick refresh, without updating SMART data
        refresh(serial,True)
    #iterate over new list of drives
    for serial,path in new_all_drives.items():
        #if not in list of drives already
        if serial not in all_drives:
            #create new drive object
            mounted=False
            if serial in mounted_drives:
                mounted=True
            drive=Drive(serial,path,mounted)
            all_drives[serial]=drive
            window['Tabgroup'].add_tab(new_tab(serial))
    window.refresh()

scan()

tabgroup = sg.TabGroup(
    [[main_tab()],[new_tab(serial) for serial in smart_data_dict.keys()]],
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

time_last_polled=0
window.write_event_value('-RefreshPage-',1)

#check for subprocess completion (shred, blkdiscard, etc) every x seconds, then send an event to refresh the current tab
def check_subproc_status():
    while not QUIT:
        print("running thread")
        for item in subproc_list:
            exitcode=item[1].poll()
            if exitcode != None:
                print("process terminated")
                if exitcode == 0:
                    all_drives[item[0]].erased=True
                item[1].terminate()
                subproc_list.remove(item)
                window.write_event_value('-RefreshPage-',1)
        time.sleep(3)
refresh_thread=threading.Thread(target=check_subproc_status)
refresh_thread.start()

while not QUIT:
    event,values=window.read()
    if event == sg.WIN_CLOSED:
        QUIT=True
        refresh_thread.join()
        break
    elif event == "-Erase-":
        drive=values['Tabgroup']
        if(drive != None):
            protocol=smart_data_dict[drive]['device']['protocol']
            subproc_list.append([drive,erase_drive(str(all_drives[drive].path),protocol)])
            refresh(drive)
    elif event == "-Long-":
        drive=values['Tabgroup']
        if(drive != None):
            t=long_test(drive,str(all_drives[drive].path),60*int(smart_data_dict[drive]['ata_smart_data']['self_test']['polling_minutes']['extended'] or 0))
            timer_list_extended.append((drive,t))
            window.write_event_value('-RefreshPage-',1)
    elif event == "-Short-":
        drive=values['Tabgroup']
        if(drive != None):
            t=short_test(drive,str(all_drives[drive].path),60*int(smart_data_dict[drive]['ata_smart_data']['self_test']['polling_minutes']['short'] or 0))
            timer_list_short.append([drive, t])
            window.write_event_value('-RefreshPage-',1)
    elif event == "-SMART-":
        drive=values['Tabgroup']
        if(drive != None):
            popup_smart_data(str(all_drives[drive].path))
    elif event == "-Refresh-":
        rescan()
        drive=values['Tabgroup']
        refresh(drive)
    elif event == "-RefreshPage-":
        drive=values['Tabgroup']
        refresh(drive)
    elif event == "-HEX-":
        drive=values['Tabgroup']
        if(drive != None):
            hexdump(str(all_drives[drive].path))
    elif event == "Tabgroup":
        drive=values['Tabgroup']
        if(drive != None):
            refresh(drive)

window.close()

