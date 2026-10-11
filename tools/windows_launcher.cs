// Give Windows Search an application-specific executable and display name.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("KaZaA")]
[assembly: AssemblyProduct("KaZaA")]
[assembly: AssemblyDescription("KaZaA desktop launcher")]
[assembly: AssemblyVersion("2.0.0.0")]

internal static class KaZaALauncher
{
    [STAThread]
    private static void Main()
    {
        string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
        try
        {
            Process.Start(new ProcessStartInfo {
                FileName = Path.Combine(root, ".venv", "Scripts", "pythonw.exe"),
                Arguments = "-m kazaa",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            });
        }
        catch (Exception error)
        {
            MessageBox.Show("Could not start KaZaA.\n" + error.Message, "KaZaA",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
