# User-invoked screen region capture. Escape cancels; no clipboard access.
param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CaptureDpi {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
}
'@
[void][CaptureDpi]::SetProcessDpiAwarenessContext([IntPtr](-4))
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$graphics.Dispose()
$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = 'None'
$form.StartPosition = 'Manual'
$form.Bounds = $bounds
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.KeyPreview = $true
$form.Cursor = [System.Windows.Forms.Cursors]::Cross
$form.BackgroundImage = $bitmap
$form.GetType().GetProperty('DoubleBuffered', [Reflection.BindingFlags]'Instance, NonPublic').SetValue($form, $true)
$script:origin = $null
$script:selection = [System.Drawing.Rectangle]::Empty
$script:accepted = $false
$form.Add_KeyDown({ if ($_.KeyCode -eq 'Escape') { $form.Close() } })
$form.Add_MouseDown({
    if ($_.Button -eq 'Left') { $script:origin = $_.Location }
})
$form.Add_MouseMove({
    if ($null -ne $script:origin) {
        $left = [Math]::Min($script:origin.X, $_.X)
        $top = [Math]::Min($script:origin.Y, $_.Y)
        $width = [Math]::Abs($script:origin.X - $_.X)
        $height = [Math]::Abs($script:origin.Y - $_.Y)
        $script:selection = New-Object System.Drawing.Rectangle $left,$top,$width,$height
        $form.Invalidate()
    }
})
$form.Add_Paint({
    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(85,0,0,0))
    $region = New-Object System.Drawing.Region $form.ClientRectangle
    $region.Exclude($script:selection)
    $_.Graphics.FillRegion($brush, $region)
    $brush.Dispose()
    $region.Dispose()
    if ($script:selection.Width -gt 0 -and $script:selection.Height -gt 0) {
        $_.Graphics.DrawRectangle([System.Drawing.Pens]::White, $script:selection)
    }
})
$form.Add_MouseUp({
    if ($_.Button -eq 'Left' -and $script:selection.Width -gt 1 -and $script:selection.Height -gt 1) {
        $script:accepted = $true
        $form.Close()
    }
})
try {
    [void]$form.ShowDialog()
    if ($script:accepted) {
        $area = [System.Drawing.Rectangle]::Intersect($script:selection, (New-Object System.Drawing.Rectangle 0,0,$bitmap.Width,$bitmap.Height))
        $result = $bitmap.Clone($area, $bitmap.PixelFormat)
        try { $result.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png) }
        finally { $result.Dispose() }
    }
} finally {
    $form.Dispose()
    $bitmap.Dispose()
}
