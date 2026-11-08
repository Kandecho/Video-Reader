"""Identity-bound cleanup of this component's abandoned host attempts."""
import os
from pathlib import Path
import subprocess
import time

from .common import ReaderError


def identity(pid):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,int(pid))
        if not handle:
            error=ctypes.get_last_error()
            if error in (87,1168):return None
            raise ReaderError('Cannot inspect previous host process identity')
        try:
            code=wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):
                raise ReaderError('Cannot inspect previous host process state')
            if code.value!=259:return None
            times=[wintypes.FILETIME() for _ in range(4)]
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
                raise ReaderError('Cannot inspect previous host process start time')
            size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
            kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
            if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
                raise ReaderError('Cannot inspect previous host executable')
            creation=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            return {'pid':int(pid),'created':creation,'executable':str(Path(buffer.value).resolve())}
        finally:kernel.CloseHandle(handle)
    path=Path('/proc')/str(pid)
    try:
        stat=(path/'stat').read_text().rsplit(')',1)[1].split()
        return {'pid':int(pid),'created':int(stat[19]),'executable':str((path/'exe').resolve())}
    except FileNotFoundError:return None


def stop_owned(record,timeout=10):
    if record is None:return {'old_host_alive':False,'cleanup':'already_exited_at_launch_record'}
    if not isinstance(record,dict) or set(record)!={'pid','created','executable'} or type(record['pid']) is not int:
        raise ReaderError('Invalid owned host process identity')
    current=identity(record['pid'])
    if current is None or current!=record:
        return {'old_host_alive':False,'cleanup':'not_running_or_pid_reused'}
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        held=kernel.OpenProcess(0x1000,False,record['pid'])
        if not held:
            if identity(record['pid'])!=record:return {'old_host_alive':False,'cleanup':'already_exited'}
            raise ReaderError('Cannot hold the owned host identity for cleanup')
        try:
            # Holding the process object also prevents a PID reuse during taskkill.
            if identity(record['pid'])!=record:return {'old_host_alive':False,'cleanup':'not_the_recorded_host'}
            result=subprocess.run(['taskkill','/PID',str(record['pid']),'/T','/F'],capture_output=True,
                                  timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode and identity(record['pid'])==record:
                raise ReaderError('Could not stop the verified abandoned host tree')
        finally:kernel.CloseHandle(held)
    else:
        import signal
        os.kill(record['pid'],signal.SIGTERM)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if identity(record['pid'])!=record:return {'old_host_alive':False,'cleanup':'verified_host_stopped'}
        time.sleep(.1)
    raise ReaderError('Previous host is still present; no replacement host started')
