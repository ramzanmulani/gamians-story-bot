# Saves the token on the clipboard as a GitHub secret of the Gamians bot, then wipes the clipboard.
#   -Kind threads : clipboard = Threads token from the User Token Generator -> THREADS_TOKEN
#   -Kind page    : clipboard = LONG-LIVED Facebook USER token (Access Token Debugger -> Extend).
#                   Only the Gamians Page's own token (never expires) is stored -> IG_ACCESS_TOKEN.
#                   No other Page (Mythical Motions) is ever saved or touched.
param([Parameter(Mandatory)][ValidateSet('threads','page')][string]$Kind)
$ErrorActionPreference = 'Continue'
$repo = 'ramzanmulani/gamians-story-bot'
$GAMIANS_PAGE = '1446723075187185'
function Fail($m) { Write-Host "  $m" -ForegroundColor Red; exit 1 }
$t = ((Get-Clipboard -Raw) -replace '\s', '')
if ($t.Length -lt 60) { Fail 'The clipboard does not hold a token. Copy it first (Ctrl+C), then run this again.' }

if ($Kind -eq 'threads') {
    try { $me = Invoke-RestMethod "https://graph.threads.net/v1.0/me?fields=username&access_token=$t" } catch { Fail "Threads refused this token: $($_.Exception.Message)" }
    if ($me.username -ne 'gamians_com') { Fail "This token is for @$($me.username), not @gamians_com. Not saved." }
    $t | gh secret set THREADS_TOKEN --repo $repo
    if ($LASTEXITCODE -ne 0) { Fail 'gh could not save the secret.' }
    Write-Host '  Threads token for @gamians_com saved.' -ForegroundColor Green
} else {
    try { $pg = Invoke-RestMethod "https://graph.facebook.com/v21.0/$($GAMIANS_PAGE)?fields=name,access_token&access_token=$t" } catch { Fail "Facebook refused this token: $($_.Exception.Message)" }
    if (-not $pg.access_token) { Fail 'No Gamians Page token came back - the token needs pages_show_list + pages_manage_posts.' }
    $dbg = Invoke-RestMethod "https://graph.facebook.com/v21.0/debug_token?input_token=$($pg.access_token)&access_token=$($pg.access_token)"
    if ($dbg.data.expires_at -ne 0) { Fail 'That Page token still expires - the user token was the short 1-hour one. Extend it in the Access Token Debugger first.' }
    $sc = $dbg.data.scopes -join ','
    if ($sc -notmatch 'pages_manage_posts') { Fail "Token is missing pages_manage_posts (has: $sc). Not saved." }
    $pg.access_token | gh secret set IG_ACCESS_TOKEN --repo $repo
    if ($LASTEXITCODE -ne 0) { Fail 'gh could not save the secret.' }
    Write-Host "  Gamians Page token saved (never expires). Scopes: $sc" -ForegroundColor Green
}
Set-Clipboard -Value ' '
Write-Host '  Clipboard wiped.'
