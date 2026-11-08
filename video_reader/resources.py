"""Small local resource sample; unknown readings never authorize background work."""
import os
import time


def sample():
    if os.name != 'nt':
        return {'available':False,'reason':'resource_probe_not_supported'}
    import ctypes
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD),
            ('total_physical',ctypes.c_ulonglong),('available_physical',ctypes.c_ulonglong),
            ('total_page',ctypes.c_ulonglong),('available_page',ctypes.c_ulonglong),
            ('total_virtual',ctypes.c_ulonglong),('available_virtual',ctypes.c_ulonglong),
            ('available_extended',ctypes.c_ulonglong)]
    def ticks():
        idle,kernel,user=wintypes.FILETIME(),wintypes.FILETIME(),wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
            raise OSError('GetSystemTimes failed')
        values=[(x.dwHighDateTime<<32)|x.dwLowDateTime for x in (idle,kernel,user)]
        return values[0],values[1]+values[2]
    try:
        first=ticks();time.sleep(.1);second=ticks()
        total=second[1]-first[1]
        if total<=0: raise OSError('CPU sample unavailable')
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise OSError('GlobalMemoryStatusEx failed')
        return {'available':True,'cpu_percent':round(100*(1-(second[0]-first[0])/total),2),
            'available_memory_mb':round(memory.available_physical/1048576), 'sample_seconds':.1}
    except OSError as error:
        return {'available':False,'reason':str(error)}
