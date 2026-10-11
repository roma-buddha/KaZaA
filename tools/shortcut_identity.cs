// Set the identity of our shortcuts without changing the shared Python launcher.
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class KaZaAShortcutIdentity
{
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropertyKey { public Guid format; public uint id; }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    struct PropVariant
    {
        [FieldOffset(0)] public ushort type;
        [FieldOffset(8)] public IntPtr value;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int Commit();
    }

    // Unused methods retain the vtable order from the Windows Search SDK.
    [ComImport, Guid("AB310581-AC80-11D1-8DF3-00C04FB6EF69"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISearchManager
    {
        void GetIndexerVersionStr(); void GetIndexerVersion(); void GetParameter();
        void SetParameter(); void GetProxyName(); void GetBypassList(); void SetProxy();
        void GetCatalog([MarshalAs(UnmanagedType.LPWStr)] string name, out ISearchCatalogManager catalog);
    }

    [ComImport, Guid("AB310581-AC80-11D1-8DF3-00C04FB6EF50"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISearchCatalogManager
    {
        void GetName(); void GetParameter(); void SetParameter(); void GetCatalogStatus(out int status, out int pausedReason);
        void Reset(); void Reindex();
        void ReindexMatchingURLs([MarshalAs(UnmanagedType.LPWStr)] string pattern);
    }

    [DllImport("ole32.dll")]
    static extern int PropVariantClear(ref PropVariant value);

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern void SHChangeNotify(uint action, uint flags, string first, string second);

    public static void Set(string path)
    {
        object link = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
        try
        {
            var file = (IPersistFile)link;
            file.Load(path, 2);
            var store = (IPropertyStore)link;
            var key = new PropertyKey { format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), id = 5 };
            var value = new PropVariant { type = 31, value = Marshal.StringToCoTaskMemUni("KaZaA.Desktop.Start1") };
            try
            {
                Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value));
                Marshal.ThrowExceptionForHR(store.Commit());
                file.Save(path, true);
            }
            finally { PropVariantClear(ref value); }
        }
        finally { Marshal.FinalReleaseComObject(link); }
    }

    public static void Notify(string path, bool deleted)
    {
        // PATHW + FLUSH: deliver the exact item event to registered Shell clients.
        SHChangeNotify(deleted ? 4u : 2u, 0x1005u, path, null);
        SHChangeNotify(0x1000u, 0x1005u, System.IO.Path.GetDirectoryName(path), null);
    }

    public static void NotifyFolder(string path)
    {
        SHChangeNotify(8u, 0x1005u, path, null);
        SHChangeNotify(0x1000u, 0x1005u, System.IO.Path.GetDirectoryName(path), null);
    }

    public static void RefreshIndex(string path)
    {
        object manager = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("7D096C5F-AC08-4F1F-BEB7-5C22C517CE39")));
        ISearchCatalogManager catalog = null;
        try
        {
            ((ISearchManager)manager).GetCatalog("SystemIndex", out catalog);
            catalog.ReindexMatchingURLs(new Uri(System.IO.Path.GetFullPath(path)).AbsoluteUri);
        }
        finally
        {
            if (catalog != null) Marshal.FinalReleaseComObject(catalog);
            Marshal.FinalReleaseComObject(manager);
        }
    }

}
