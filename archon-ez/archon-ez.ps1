$ErrorActionPreference = "Stop"

function Write-Header([string]$text) {
  Write-Host ""
  Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Write-Warn([string]$text) {
  Write-Host $text -ForegroundColor Yellow
}

function Write-Dim([string]$text) {
  Write-Host $text -ForegroundColor DarkGray
}

function Assert-ArchonInstalled {
  $cmd = Get-Command archon -ErrorAction SilentlyContinue
  if (-not $cmd) {
    throw "Archon is not installed or not on PATH. Try reinstalling Archon, then re-run."
  }
}

function Get-BaseDir {
  Split-Path -Parent $MyInvocation.MyCommand.Path
}

function Get-ConfigPath {
  Join-Path (Get-BaseDir) "config.archon.yaml"
}

function Get-SettingsPath {
  Join-Path (Get-BaseDir) "settings.json"
}

function Load-Settings {
  $path = Get-SettingsPath
  if (-not (Test-Path $path)) {
    return [pscustomobject]@{
      advanced_mode = $false
      updated_at = (Get-Date).ToString("o")
    }
  }
  try {
    return (Get-Content -Raw -Path $path) | ConvertFrom-Json -ErrorAction Stop
  } catch {
    return [pscustomobject]@{
      advanced_mode = $false
      updated_at = (Get-Date).ToString("o")
    }
  }
}

function Save-Settings($settings) {
  $settings.updated_at = (Get-Date).ToString("o")
  ($settings | ConvertTo-Json -Depth 6) | Set-Content -Path (Get-SettingsPath) -Encoding UTF8
}

function Ensure-Config {
  $configPath = Get-ConfigPath
  if (Test-Path $configPath) { return $configPath }

  Write-Header "One-time setup"
  Write-Host "Creating Archon config at: $configPath"
  & archon init --config $configPath | Out-Host
  if (-not (Test-Path $configPath)) {
    throw "Config was not created. Expected: $configPath"
  }
  return $configPath
}

function Ensure-Server([string]$configPath, [string]$baseUrl = "http://127.0.0.1:8000") {
  $healthy = $false
  try {
    & archon health --base-url $baseUrl --timeout 2.5 | Out-Null
    $healthy = $true
  } catch {
    $healthy = $false
  }

  if ($healthy) { return }

  Write-Header "Starting Archon server"
  Write-Host "Launching: archon serve --kill-port --config `"$configPath`""
  $proc = Start-Process -FilePath "archon" -ArgumentList @("serve", "--kill-port", "--config", $configPath) -PassThru -WindowStyle Minimized

  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 800
    try {
      & archon health --base-url $baseUrl --timeout 2.5 | Out-Null
      Write-Host "Server is healthy. (PID: $($proc.Id))"
      return
    } catch {
      # keep waiting
    }
  }

  Write-Warn "Server did not become healthy within 30s."
  Write-Warn "Try running manually: archon serve --kill-port --config `"$configPath`""
  throw "Archon server not healthy."
}

function New-Slug([string]$text) {
  $slug = ($text -replace "[^a-zA-Z0-9]+", "-").Trim("-").ToLowerInvariant()
  if ([string]::IsNullOrWhiteSpace($slug)) { $slug = "mission" }
  if ($slug.Length -gt 48) { $slug = $slug.Substring(0, 48).Trim("-") }
  return $slug
}

function Read-Template([string]$templatePath, [hashtable]$vars) {
  $content = Get-Content -Raw -Path $templatePath
  foreach ($k in $vars.Keys) {
    $content = $content.Replace("{{${k}}}", [string]$vars[$k])
  }
  return $content
}

function Create-Mission {
  Write-Header "New mission"

  $goal = Read-Host "In one sentence, what do you want to achieve?"
  if ([string]::IsNullOrWhiteSpace($goal)) { throw "Goal is required." }

  $deadline = Read-Host "Any deadline? (optional)"
  $doneDefinition = Read-Host "What does 'done' look like? (optional)"
  $constraints = Read-Host "Any constraints / must-not-do? (optional)"
  $resources = Read-Host "What resources do you have (people, links, accounts)? (optional)"
  $notes = Read-Host "Anything else? (optional)"

  $baseDir = Get-BaseDir
  $missionsDir = Join-Path $baseDir "missions"
  New-Item -ItemType Directory -Path $missionsDir -Force | Out-Null

  $ts = Get-Date -Format "yyyyMMdd-HHmmss"
  $slug = New-Slug $goal
  $missionDir = Join-Path $missionsDir "$ts-$slug"
  New-Item -ItemType Directory -Path $missionDir -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $missionDir "history") -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $missionDir "outputs") -Force | Out-Null

  $templatePath = Join-Path $baseDir "templates\\brief.default.md"
  $brief = Read-Template -templatePath $templatePath -vars @{
    GOAL = $goal
    DEADLINE = $deadline
    DONE_DEFINITION = $doneDefinition
    CONSTRAINTS = $constraints
    RESOURCES = $resources
    NOTES = $notes
  }

  $briefPath = Join-Path $missionDir "brief.md"
  Set-Content -Path $briefPath -Value $brief -Encoding UTF8

  Write-Host "Created mission at: $missionDir"
  return @{
    goal = $goal
    dir = $missionDir
    briefPath = $briefPath
  }
}

function Try-ExtractJson([string]$text) {
  # Best-effort: strip any leading/trailing noise.
  $start = $text.IndexOf("{")
  $end = $text.LastIndexOf("}")
  if ($start -lt 0 -or $end -le $start) { return $null }
  return $text.Substring($start, $end - $start + 1)
}

function Invoke-ArchonTask([string]$goal, [string]$contextFile, [string]$mode = "auto") {
  $out = & archon task --mode $mode --context-file $contextFile $goal 2>&1 | Out-String
  return $out.Trim()
}

function Confirm-Phrase([string]$phrase, [string]$prompt) {
  Write-Host ""
  Write-Warn $prompt
  $typed = Read-Host "Type '$phrase' to continue (or anything else to cancel)"
  return ($typed -eq $phrase)
}

function Ensure-MissionDirs([string]$missionDir) {
  New-Item -ItemType Directory -Path (Join-Path $missionDir "history") -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $missionDir "outputs") -Force | Out-Null
}

function Get-ConnectorCatalog {
  return @(
    "email_draft"
    "calendar_ics"
    "whatsapp_message"
    "slack_message"
    "browser_checklist"
    "csv_export"
    "text_draft"
    "markdown_draft"
    "file_write"
    "shell_command"
    "none"
  )
}

function Pick-Connector([string]$default = "email_draft") {
  Write-Header "Pick connector"
  $catalog = Get-ConnectorCatalog
  for ($i = 0; $i -lt $catalog.Count; $i++) {
    $label = $catalog[$i]
    $suffix = if ($label -eq $default) { " (default)" } else { "" }
    Write-Host ("{0}) {1}{2}" -f ($i + 1), $label, $suffix)
  }
  $pick = Read-Host "Choose (1-$($catalog.Count)) or Enter for default"
  if ([string]::IsNullOrWhiteSpace($pick)) { return $default }
  $idx = [int]$pick - 1
  if ($idx -lt 0 -or $idx -ge $catalog.Count) { return $default }
  return $catalog[$idx]
}

function Generate-Plan($mission, [string]$configPath) {
  Ensure-Server -configPath $configPath

  Write-Header "Planning"
  $planPrompt = @"
You are a planning+execution assistant for a non-technical user.
Return STRICT JSON ONLY (no markdown, no extra text) that matches:
{
  "outcome": "string",
  "assumptions": ["string"],
  "steps": [
    {
      "id": 1,
      "title": "string",
      "why": "string",
      "how": "string",
      "owner": "user|archon",
      "time_minutes": 10,
      "connector": "email_draft|calendar_ics|whatsapp_message|slack_message|browser_checklist|csv_export|text_draft|markdown_draft|file_write|shell_command|none",
      "inputs_needed": ["string"],
      "success_criteria": "string",
      "done": false
    }
  ],
  "first_question": "string"
}

Mission: $($mission.goal)
"@

  $raw = Invoke-ArchonTask -goal $planPrompt -contextFile $mission.briefPath

  $historyPath = Join-Path $mission.dir ("history\\plan-raw-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
  Set-Content -Path $historyPath -Value $raw -Encoding UTF8

  $jsonText = Try-ExtractJson $raw
  if (-not $jsonText) {
    Write-Warn "Could not find JSON in Archon output. Saved raw output to history."
    return $null
  }

  try {
    $planObj = $jsonText | ConvertFrom-Json -ErrorAction Stop
  } catch {
    Write-Warn "JSON parse failed. Saved raw output to history."
    return $null
  }

  $planPath = Join-Path $mission.dir "plan.json"
  ($planObj | ConvertTo-Json -Depth 12) | Set-Content -Path $planPath -Encoding UTF8

  $statusPath = Join-Path $mission.dir "status.json"
  if (-not (Test-Path $statusPath)) {
    $status = @{
      done_step_ids = @()
      artifacts = @()
      updated_at = (Get-Date).ToString("o")
    }
    ($status | ConvertTo-Json -Depth 6) | Set-Content -Path $statusPath -Encoding UTF8
  }

  Write-Host "Saved plan: $planPath"
  if ($planObj.first_question) {
    Write-Host ""
    Write-Host "Question:" -ForegroundColor Green
    Write-Host $planObj.first_question
  }
  return $planObj
}

function Load-JsonFile([string]$path) {
  (Get-Content -Raw -Path $path) | ConvertFrom-Json
}

function Save-JsonFile([string]$path, $obj, [int]$depth = 12) {
  ($obj | ConvertTo-Json -Depth $depth) | Set-Content -Path $path -Encoding UTF8
}

function Show-Steps($planObj, $statusObj) {
  Write-Host ""
  foreach ($s in $planObj.steps) {
    $done = $statusObj.done_step_ids -contains $s.id
    $box = if ($done) { "[x]" } else { "[ ]" }
    $owner = if ($s.owner) { $s.owner } else { "user" }
    $connector = if ($s.connector) { $s.connector } else { "none" }
    Write-Host ("{0} {1,2}. {2}  ({3})  <{4}>" -f $box, $s.id, $s.title, $owner, $connector)
  }
}

function Add-Artifact($statusObj, [int]$stepId, [string]$connector, [string]$path, [string]$summary) {
  if (-not $statusObj.artifacts) { $statusObj | Add-Member -NotePropertyName "artifacts" -NotePropertyValue @() }
  $statusObj.artifacts += [pscustomobject]@{
    step_id = $stepId
    connector = $connector
    path = $path
    summary = $summary
    created_at = (Get-Date).ToString("o")
  }
  $statusObj.updated_at = (Get-Date).ToString("o")
}

function Write-EmailArtifacts([string]$outputsDir, [int]$stepId, $payload) {
  $to = @()
  if ($payload.to) { $to = @($payload.to) }
  if ($to -isnot [System.Array]) { $to = @($to) }
  $subject = [string]($payload.subject ?? "")
  $body = [string]($payload.body ?? "")

  $txtPath = Join-Path $outputsDir ("step-$stepId-email.txt")
  $emlPath = Join-Path $outputsDir ("step-$stepId-email.eml")

  $txt = @()
  $txt += "TO: " + ($to -join ", ")
  if ($payload.cc) { $txt += "CC: " + (@($payload.cc) -join ", ") }
  $txt += "SUBJECT: " + $subject
  $txt += ""
  $txt += $body
  ($txt -join "`r`n") | Set-Content -Path $txtPath -Encoding UTF8

  $eml = @()
  if ($to.Count -gt 0) { $eml += "To: " + ($to -join ", ") }
  if ($payload.cc) { $eml += "Cc: " + (@($payload.cc) -join ", ") }
  $eml += "Subject: " + $subject
  $eml += "MIME-Version: 1.0"
  $eml += "Content-Type: text/plain; charset=utf-8"
  $eml += ""
  $eml += $body
  ($eml -join "`r`n") | Set-Content -Path $emlPath -Encoding UTF8

  return @($txtPath, $emlPath)
}

function To-IcsUtc([datetime]$dt) {
  $utc = $dt.ToUniversalTime()
  return $utc.ToString("yyyyMMdd'T'HHmmss'Z'")
}

function Write-CalendarIcs([string]$outputsDir, [int]$stepId, $payload) {
  $title = [string]($payload.title ?? "Event")
  $desc = [string]($payload.description ?? "")
  $location = [string]($payload.location ?? "")
  $startIso = [string]($payload.start_iso ?? "")
  $endIso = [string]($payload.end_iso ?? "")

  if ([string]::IsNullOrWhiteSpace($startIso) -or [string]::IsNullOrWhiteSpace($endIso)) {
    throw "calendar_ics requires start_iso and end_iso."
  }

  $start = [datetime]::Parse($startIso, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
  $end = [datetime]::Parse($endIso, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)

  $uid = [guid]::NewGuid().ToString()
  $dtstamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd'T'HHmmss'Z'")
  $icsPath = Join-Path $outputsDir ("step-$stepId-event.ics")

  $lines = @()
  $lines += "BEGIN:VCALENDAR"
  $lines += "VERSION:2.0"
  $lines += "PRODID:-//Archon EZ//EN"
  $lines += "CALSCALE:GREGORIAN"
  $lines += "BEGIN:VEVENT"
  $lines += "UID:$uid"
  $lines += "DTSTAMP:$dtstamp"
  $lines += "DTSTART:" + (To-IcsUtc $start)
  $lines += "DTEND:" + (To-IcsUtc $end)
  $lines += "SUMMARY:" + ($title -replace "`r?`n", " ")
  if (-not [string]::IsNullOrWhiteSpace($location)) { $lines += "LOCATION:" + ($location -replace "`r?`n", " ") }
  if (-not [string]::IsNullOrWhiteSpace($desc)) { $lines += "DESCRIPTION:" + ($desc -replace "`r?`n", "\\n") }
  $lines += "END:VEVENT"
  $lines += "END:VCALENDAR"

  ($lines -join "`r`n") | Set-Content -Path $icsPath -Encoding UTF8
  return $icsPath
}

function Write-TextOutput([string]$outputsDir, [int]$stepId, [string]$name, [string]$content) {
  $path = Join-Path $outputsDir ("step-$stepId-$name.txt")
  $content | Set-Content -Path $path -Encoding UTF8
  return $path
}

function Write-MarkdownOutput([string]$outputsDir, [int]$stepId, [string]$name, [string]$content) {
  $path = Join-Path $outputsDir ("step-$stepId-$name.md")
  $content | Set-Content -Path $path -Encoding UTF8
  return $path
}

function Write-CsvOutput([string]$outputsDir, [int]$stepId, $payload) {
  $filename = [string]($payload.filename ?? ("step-$stepId-export.csv"))
  $safeName = ($filename -replace '[\\/:*?"<>|]+', '-')
  $path = Join-Path $outputsDir $safeName

  $headers = @($payload.headers)
  if (-not $headers -or $headers.Count -eq 0) { throw "csv_export requires headers" }
  $rows = @($payload.rows)
  if (-not $rows) { $rows = @() }

  $sb = New-Object System.Text.StringBuilder
  [void]$sb.AppendLine(($headers | ForEach-Object { '"' + ([string]$_).Replace('"','""') + '"' }) -join ",")
  foreach ($r in $rows) {
    $cells = @()
    foreach ($h in $headers) {
      $val = ""
      try { $val = [string]($r.$h) } catch { $val = "" }
      $cells += '"' + $val.Replace('"','""') + '"'
    }
    [void]$sb.AppendLine(($cells -join ","))
  }
  $sb.ToString() | Set-Content -Path $path -Encoding UTF8
  return $path
}

function Write-FilesToMission([string]$missionDir, [int]$stepId, $payload, [bool]$requireConfirm = $true) {
  $files = @($payload.files)
  if (-not $files -or $files.Count -eq 0) { throw "file_write requires files[]" }

  if ($requireConfirm) {
    $ok = Confirm-Phrase -phrase "WRITE" -prompt "This will write $($files.Count) file(s) into the mission folder."
    if (-not $ok) { return @() }
  }

  $written = @()
  foreach ($f in $files) {
    $rel = [string]($f.relative_path ?? "")
    if ([string]::IsNullOrWhiteSpace($rel)) { continue }
    if ($rel.Contains("..")) { throw "Refusing path traversal: $rel" }
    $target = Join-Path $missionDir $rel
    $parent = Split-Path -Parent $target
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    [string]($f.content ?? "") | Set-Content -Path $target -Encoding UTF8
    $written += $target
  }
  return $written
}

function Maybe-RunShellCommand([string]$missionDir, [int]$stepId, $payload, $settings) {
  if (-not $settings.advanced_mode) {
    Write-Warn "Advanced mode is OFF. Shell execution is disabled."
    return $null
  }
  $cmd = [string]($payload.command ?? "")
  if ([string]::IsNullOrWhiteSpace($cmd)) { throw "shell_command requires command" }
  $ok = Confirm-Phrase -phrase "RUN" -prompt "This will run a command on your computer and save output in the mission history."
  if (-not $ok) { return $null }

  $historyPath = Join-Path $missionDir ("history\\shell-step-$stepId-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
  $out = & pwsh -NoProfile -Command $cmd 2>&1 | Out-String
  Set-Content -Path $historyPath -Value $out -Encoding UTF8
  return $historyPath
}

function Normalize-ArtifactResponse($obj) {
  if ($null -eq $obj) { return $null }
  if ($obj.type -and $obj.payload) {
    return [pscustomobject]@{ type = [string]$obj.type; payload = $obj.payload }
  }
  if ($obj.connector -and $obj.payload) {
    return [pscustomobject]@{ type = [string]$obj.connector; payload = $obj.payload }
  }
  if ($obj.filename -and $obj.content) {
    return [pscustomobject]@{ type = "text_draft"; payload = $obj }
  }
  if ($obj.email -or $obj.subject -or $obj.body) {
    return [pscustomobject]@{ type = "email_draft"; payload = $obj }
  }
  if ($obj.start_iso -or $obj.end_iso) {
    return [pscustomobject]@{ type = "calendar_ics"; payload = $obj }
  }
  if ($obj.files) {
    return [pscustomobject]@{ type = "file_write"; payload = $obj }
  }
  if ($obj.command) {
    return [pscustomobject]@{ type = "shell_command"; payload = $obj }
  }
  return $null
}

function Generate-ArtifactForStep([string]$missionDir, [string]$briefPath, $planObj, $step, [string]$connector, [string]$configPath, $statusObj, $settings) {
  Ensure-Server -configPath $configPath
  Ensure-MissionDirs -missionDir $missionDir

  $outputsDir = Join-Path $missionDir "outputs"
  $id = [int]$step.id

  if ($connector -eq "none") {
    Write-Dim "No connector for this step."
    return
  }

  $artifactPrompt = @"
You generate execution artifacts for non-technical users.
Return STRICT JSON ONLY (no markdown, no extra text).

Connector: $connector

Return one of these shapes:
1) {"type":"email_draft","payload":{"to":["person@example.com"],"cc":[],"subject":"...","body":"..."}}
2) {"type":"calendar_ics","payload":{"title":"...","description":"...","start_iso":"2026-03-13T10:00:00+05:30","end_iso":"2026-03-13T10:30:00+05:30","location":"..."}}
3) {"type":"whatsapp_message","payload":{"message":"..."}}
4) {"type":"slack_message","payload":{"channel":"#channel-or-person","message":"..."}}
5) {"type":"browser_checklist","payload":{"checklist_md":"# ...\\n- [ ] ..."}}
6) {"type":"csv_export","payload":{"filename":"export.csv","headers":["col1","col2"],"rows":[{"col1":"a","col2":"b"}]}}
7) {"type":"text_draft","payload":{"filename":"draft.txt","content":"..."}}
8) {"type":"markdown_draft","payload":{"filename":"draft.md","content":"..."}}
9) {"type":"file_write","payload":{"files":[{"relative_path":"outputs/note.txt","content":"..."}]}}
10) {"type":"shell_command","payload":{"command":"..."}}

Mission outcome: $([string]($planObj.outcome ?? ""))
Step: [$($step.id)] $($step.title)
Why: $([string]($step.why ?? ""))
How: $([string]($step.how ?? ""))
Inputs needed: $([string]::Join(", ", @($step.inputs_needed)))
Success criteria: $([string]($step.success_criteria ?? ""))
"@

  $raw = Invoke-ArchonTask -goal $artifactPrompt -contextFile $briefPath
  $historyPath = Join-Path $missionDir ("history\\artifact-step-$id-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
  Set-Content -Path $historyPath -Value $raw -Encoding UTF8

  $jsonText = Try-ExtractJson $raw
  if (-not $jsonText) {
    Write-Warn "Could not parse JSON. Raw output saved in history."
    return
  }

  $obj = $null
  try { $obj = $jsonText | ConvertFrom-Json -ErrorAction Stop } catch { $obj = $null }
  if (-not $obj) {
    Write-Warn "JSON parse failed. Raw output saved in history."
    return
  }

  $norm = Normalize-ArtifactResponse $obj
  if (-not $norm) {
    Write-Warn "Unrecognized artifact JSON. Raw output saved in history."
    return
  }

  $type = $norm.type
  $payload = $norm.payload

  try {
    switch ($type) {
      "email_draft" {
        $paths = Write-EmailArtifacts -outputsDir $outputsDir -stepId $id -payload $payload
        foreach ($p in $paths) { Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Email draft" }
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $($paths -join ', ')"
      }
      "calendar_ics" {
        $p = Write-CalendarIcs -outputsDir $outputsDir -stepId $id -payload $payload
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Calendar invite"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "whatsapp_message" {
        $p = Write-TextOutput -outputsDir $outputsDir -stepId $id -name "whatsapp" -content ([string]($payload.message ?? ""))
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "WhatsApp message"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "slack_message" {
        $content = "CHANNEL: " + [string]($payload.channel ?? "") + "`r`n`r`n" + [string]($payload.message ?? "")
        $p = Write-TextOutput -outputsDir $outputsDir -stepId $id -name "slack" -content $content
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Slack message"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "browser_checklist" {
        $p = Write-MarkdownOutput -outputsDir $outputsDir -stepId $id -name "browser" -content ([string]($payload.checklist_md ?? ""))
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Browser checklist"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "csv_export" {
        $p = Write-CsvOutput -outputsDir $outputsDir -stepId $id -payload $payload
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "CSV export"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "text_draft" {
        $filename = [string]($payload.filename ?? ("step-$id-draft.txt"))
        $safeName = ($filename -replace '[\\/:*?"<>|]+', '-')
        $p = Join-Path $outputsDir $safeName
        [string]($payload.content ?? "") | Set-Content -Path $p -Encoding UTF8
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Text draft"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "markdown_draft" {
        $filename = [string]($payload.filename ?? ("step-$id-draft.md"))
        $safeName = ($filename -replace '[\\/:*?"<>|]+', '-')
        $p = Join-Path $outputsDir $safeName
        [string]($payload.content ?? "") | Set-Content -Path $p -Encoding UTF8
        Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Markdown draft"
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        Write-Host "Saved: $p"
      }
      "file_write" {
        $written = Write-FilesToMission -missionDir $missionDir -stepId $id -payload $payload -requireConfirm $true
        foreach ($p in $written) { Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "File written" }
        Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
        if ($written.Count -gt 0) { Write-Host "Wrote: $($written -join ', ')" }
      }
      "shell_command" {
        $p = Maybe-RunShellCommand -missionDir $missionDir -stepId $id -payload $payload -settings $settings
        if ($p) {
          Add-Artifact -statusObj $statusObj -stepId $id -connector $type -path $p -summary "Shell output"
          Save-JsonFile -path (Join-Path $missionDir "status.json") -obj $statusObj
          Write-Host "Saved: $p"
        }
      }
      default {
        Write-Warn "Connector not implemented: $type"
      }
    }
  } catch {
    Write-Warn ("Artifact generation failed: " + $_.Exception.Message)
  }
}

function Mission-ExecuteLoop([string]$missionDir, [string]$configPath) {
  $briefPath = Join-Path $missionDir "brief.md"
  $planPath = Join-Path $missionDir "plan.json"
  $statusPath = Join-Path $missionDir "status.json"

  if (-not (Test-Path $briefPath)) { throw "Missing brief: $briefPath" }
  if (-not (Test-Path $planPath)) { throw "Missing plan: $planPath" }
  if (-not (Test-Path $statusPath)) {
    Save-JsonFile -path $statusPath -obj @{ done_step_ids = @(); artifacts = @(); updated_at = (Get-Date).ToString("o") }
  }

  Ensure-Server -configPath $configPath
  Ensure-MissionDirs -missionDir $missionDir
  $settings = Load-Settings

  $planObj = Load-JsonFile $planPath
  $statusObj = Load-JsonFile $statusPath

  while ($true) {
    Write-Header "Execute mission"
    Write-Host "Mission: $missionDir"
    Show-Steps -planObj $planObj -statusObj $statusObj

    Write-Host ""
    Write-Host "Options:"
    Write-Host "  1) Mark step done"
    Write-Host "  2) Get help on a step"
    Write-Host "  3) Create an artifact for a step (connector)"
    Write-Host "  4) Create artifacts for all pending steps"
    Write-Host "  5) Re-plan (overwrite plan.json)"
    Write-Host "  6) Open mission folder"
    Write-Host "  7) Settings (toggle advanced mode)"
    Write-Host "  8) Exit"
    $choice = Read-Host "Choose (1-8)"

    switch ($choice) {
      "1" {
        $id = [int](Read-Host "Step id to mark done")
        if ($statusObj.done_step_ids -notcontains $id) {
          $statusObj.done_step_ids += $id
          $statusObj.updated_at = (Get-Date).ToString("o")
          Save-JsonFile -path $statusPath -obj $statusObj
        }
      }
      "2" {
        $id = [int](Read-Host "Step id to get help with")
        $step = $planObj.steps | Where-Object { $_.id -eq $id } | Select-Object -First 1
        if (-not $step) {
          Write-Warn "No such step id: $id"
          Start-Sleep -Seconds 1
          break
        }

        $helpPrompt = @"
You are helping a non-technical user execute ONE step safely.
Return STRICT JSON ONLY:
{
  "instruction": "1-3 short sentences",
  "template": "optional text the user can copy/paste",
  "confirm_question": "one yes/no question"
}

Mission: $(($planObj.outcome) ?? "")
Current step: [$($step.id)] $($step.title)
Why: $($step.why)
How: $($step.how)
Connector: $($step.connector)
Already done step ids: $([string]::Join(',', $statusObj.done_step_ids))
"@

        $raw = Invoke-ArchonTask -goal $helpPrompt -contextFile $briefPath
        $historyPath = Join-Path $missionDir ("history\\help-step-$id-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
        Set-Content -Path $historyPath -Value $raw -Encoding UTF8

        $jsonText = Try-ExtractJson $raw
        if (-not $jsonText) {
          Write-Warn "Could not parse JSON. Showing raw output:"
          Write-Host $raw
          Read-Host "Press Enter to continue" | Out-Null
          break
        }

        try {
          $helpObj = $jsonText | ConvertFrom-Json -ErrorAction Stop
          Write-Host ""
          Write-Host $helpObj.instruction -ForegroundColor Green
          if ($helpObj.template) {
            Write-Host ""
            Write-Host "Template:" -ForegroundColor Cyan
            Write-Host $helpObj.template
          }
          if ($helpObj.confirm_question) {
            Write-Host ""
            Write-Host ("Confirm: " + $helpObj.confirm_question) -ForegroundColor Yellow
          }
          Read-Host "Press Enter to continue" | Out-Null
        } catch {
          Write-Warn "JSON parse failed. Showing raw output:"
          Write-Host $raw
          Read-Host "Press Enter to continue" | Out-Null
        }
      }
      "3" {
        $id = [int](Read-Host "Step id to create an artifact for")
        $step = $planObj.steps | Where-Object { $_.id -eq $id } | Select-Object -First 1
        if (-not $step) {
          Write-Warn "No such step id: $id"
          Start-Sleep -Seconds 1
          break
        }
        $connector = if ($step.connector) { [string]$step.connector } else { Pick-Connector }
        if ([string]::IsNullOrWhiteSpace($connector)) { $connector = Pick-Connector }
        Generate-ArtifactForStep -missionDir $missionDir -briefPath $briefPath -planObj $planObj -step $step -connector $connector -configPath $configPath -statusObj $statusObj -settings $settings
        $statusObj = Load-JsonFile $statusPath
        Read-Host "Press Enter to continue" | Out-Null
      }
      "4" {
        foreach ($s in $planObj.steps) {
          $sid = [int]$s.id
          if ($statusObj.done_step_ids -contains $sid) { continue }
          $connector = if ($s.connector) { [string]$s.connector } else { "none" }
          if ($connector -eq "none") { continue }
          Write-Header ("Artifact: step $sid")
          Generate-ArtifactForStep -missionDir $missionDir -briefPath $briefPath -planObj $planObj -step $s -connector $connector -configPath $configPath -statusObj $statusObj -settings $settings
          $statusObj = Load-JsonFile $statusPath
        }
        Read-Host "Done. Press Enter to continue" | Out-Null
      }
      "5" {
        $mission = @{
          goal = (Get-Content -Raw -Path $briefPath | Select-String -Pattern "^## Goal" -Context 0,2 | ForEach-Object { $_.Context.PostContext -join "`n" }).Trim()
          dir = $missionDir
          briefPath = $briefPath
        }
        Generate-Plan -mission $mission -configPath $configPath | Out-Null
        $planObj = Load-JsonFile $planPath
      }
      "6" {
        Invoke-Item $missionDir
      }
      "7" {
        Write-Header "Settings"
        Write-Host ("Advanced mode: " + ($settings.advanced_mode ? "ON" : "OFF"))
        Write-Dim "Advanced mode enables running shell commands from connectors."
        $toggle = Read-Host "Toggle advanced mode? (y/N)"
        if ($toggle -match "^(y|yes)$") {
          $settings.advanced_mode = -not [bool]$settings.advanced_mode
          Save-Settings $settings
          Write-Host ("Advanced mode is now: " + ($settings.advanced_mode ? "ON" : "OFF"))
        }
        Read-Host "Press Enter to continue" | Out-Null
      }
      "8" { return }
      default { }
    }
  }
}

function Select-ExistingMission {
  $missionsDir = Join-Path (Get-BaseDir) "missions"
  if (-not (Test-Path $missionsDir)) {
    Write-Warn "No missions found yet."
    return $null
  }
  $dirs = Get-ChildItem -Directory -Path $missionsDir | Sort-Object Name -Descending
  if (-not $dirs -or $dirs.Count -eq 0) {
    Write-Warn "No missions found yet."
    return $null
  }
  Write-Header "Pick a mission"
  for ($i = 0; $i -lt [Math]::Min($dirs.Count, 15); $i++) {
    Write-Host ("{0}) {1}" -f ($i + 1), $dirs[$i].Name)
  }
  $pick = Read-Host "Choose (1-$([Math]::Min($dirs.Count, 15)))"
  $idx = [int]$pick - 1
  if ($idx -lt 0 -or $idx -ge [Math]::Min($dirs.Count, 15)) { return $null }
  return $dirs[$idx].FullName
}

function Main {
  Assert-ArchonInstalled
  $configPath = Ensure-Config

  while ($true) {
    Write-Header "Archon EZ"
    Write-Host "1) New mission (plan + execute)"
    Write-Host "2) Continue an existing mission"
    Write-Host "3) Start server (if needed)"
    Write-Host "4) Exit"
    $choice = Read-Host "Choose (1-4)"

    switch ($choice) {
      "1" {
        $mission = Create-Mission
        Generate-Plan -mission $mission -configPath $configPath | Out-Null
        Mission-ExecuteLoop -missionDir $mission.dir -configPath $configPath
      }
      "2" {
        $dir = Select-ExistingMission
        if ($dir) { Mission-ExecuteLoop -missionDir $dir -configPath $configPath }
      }
      "3" {
        Ensure-Server -configPath $configPath
        Read-Host "Server healthy. Press Enter to continue" | Out-Null
      }
      "4" { return }
      default { }
    }
  }
}

Main
