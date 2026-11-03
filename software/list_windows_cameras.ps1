# Enumerate DirectShow capture-device metadata only. Does not open a camera.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if (-not ('PynqCameraInventory' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("29840822-5B84-11D0-BD3B-00A0C911CE86"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPynqCreateDevEnum {
    [PreserveSig] int CreateClassEnumerator(ref Guid category, out IEnumMoniker enumerator, int flags);
}
[ComImport, Guid("55272A00-42CB-11CE-8135-00AA004BB851"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPynqPropertyBag {
    [PreserveSig] int Read([MarshalAs(UnmanagedType.LPWStr)] string name,
        [In, Out, MarshalAs(UnmanagedType.Struct)] ref object value, IntPtr errorLog);
    [PreserveSig] int Write([MarshalAs(UnmanagedType.LPWStr)] string name,
        [In, MarshalAs(UnmanagedType.Struct)] ref object value);
}
public class PynqCameraItem {
    public int index {get;set;}
    public string name {get;set;}
    public string path {get;set;}
}
public static class PynqCameraInventory {
    public static PynqCameraItem[] Get() {
        object devObject=null;
        IEnumMoniker enumerator=null;
        var result=new List<PynqCameraItem>();
        try {
            devObject=Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")));
            var devices=(IPynqCreateDevEnum)devObject;
            var category=new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
            int code=devices.CreateClassEnumerator(ref category,out enumerator,0);
            if (code==1) return result.ToArray();
            Marshal.ThrowExceptionForHR(code);
            var monikers=new IMoniker[1];
            int index=0;
            while (enumerator.Next(1,monikers,IntPtr.Zero)==0) {
                object storage=null;
                try {
                    var bagId=new Guid("55272A00-42CB-11CE-8135-00AA004BB851");
                    monikers[0].BindToStorage(null,null,ref bagId,out storage);
                    var bag=(IPynqPropertyBag)storage;
                    object name=null,path=null;
                    Marshal.ThrowExceptionForHR(bag.Read("FriendlyName",ref name,IntPtr.Zero));
                    int pathCode=bag.Read("DevicePath",ref path,IntPtr.Zero);
                    string pathText=pathCode>=0 ? Convert.ToString(path) : "";
                    result.Add(new PynqCameraItem {index=index,name=Convert.ToString(name),path=pathText});
                } finally {
                    if (storage!=null) Marshal.ReleaseComObject(storage);
                    if (monikers[0]!=null) Marshal.ReleaseComObject(monikers[0]);
                }
                index++;
            }
            return result.ToArray();
        } finally {
            if (enumerator!=null) Marshal.ReleaseComObject(enumerator);
            if (devObject!=null) Marshal.ReleaseComObject(devObject);
        }
    }
}
'@
}
$pynqCameraItems=@([PynqCameraInventory]::Get())
ConvertTo-Json -InputObject $pynqCameraItems -Depth 4 -Compress
