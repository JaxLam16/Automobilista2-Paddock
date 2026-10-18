# Paddock speech host: Windows' built-in text-to-speech and, for push-to-talk, speech
# recognition limited to the reply phrases (System.Speech). One JSON request per line on
# stdin, one JSON reply per line on stdout. Started hidden by ams2season/coach/speech.py and
# closed when its stdin closes. The microphone is used only between listen_start and
# listen_stop (while the radio button is held). No network, no files written.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @"
using System;
using System.Speech.Recognition;
using System.Threading;
public class PaddockListener : IDisposable {
    private SpeechRecognitionEngine engine;
    private ManualResetEvent done = new ManualResetEvent(true);
    private bool active;
    public string Text;
    public float Confidence;
    public string Error;
    public bool DetectedSpeech;
    public PaddockListener(string[] phrases) {
        RecognizerInfo english = null;
        foreach (RecognizerInfo info in SpeechRecognitionEngine.InstalledRecognizers()) {
            if (info.Culture.TwoLetterISOLanguageName != "en") continue;
            if (english == null || info.Culture.Equals(System.Globalization.CultureInfo.CurrentCulture)) english = info;
        }
        if (english == null) throw new InvalidOperationException("Install Windows English speech recognition to use Paddock push-to-talk.");
        engine = new SpeechRecognitionEngine(english);
        GrammarBuilder grammar = new GrammarBuilder(new Choices(phrases));
        grammar.Culture = english.Culture;
        engine.LoadGrammar(new Grammar(grammar));
        engine.SpeechRecognized += OnRecognized;
        engine.SpeechDetected += (sender, args) => { DetectedSpeech = true; };
        engine.SpeechRecognitionRejected += (sender, args) => { DetectedSpeech = true; };
        engine.RecognizeCompleted += OnCompleted;
    }
    private void OnRecognized(object sender, SpeechRecognizedEventArgs e) {
        if (e.Result != null && e.Result.Confidence >= Confidence) { Text = e.Result.Text; Confidence = e.Result.Confidence; }
    }
    private void OnCompleted(object sender, RecognizeCompletedEventArgs e) {
        if (e.Error != null) { Error = e.Error.Message; }
        done.Set();
    }
    public void Start() {
        if (active) { return; }
        // Grammar may be prepared before PTT; open the microphone only here.
        engine.SetInputToDefaultAudioDevice();
        Text = null; Confidence = 0; Error = null; DetectedSpeech = false; done.Reset(); active = true;
        engine.RecognizeAsync(RecognizeMode.Multiple);
    }
    public void Stop(int waitMs) {
        if (!active) { return; }
        try {
            engine.RecognizeAsyncStop();
            if (!done.WaitOne(waitMs)) {
                engine.RecognizeAsyncCancel();
                throw new TimeoutException("Speech recognition did not finish. Press the radio button and try again.");
            }
            engine.SetInputToNull();
        } finally {
            active = false;
        }
    }
    public void Dispose() { engine.Dispose(); done.Dispose(); }
}
"@
$listener = $null

function Send($value) {
    [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress -Depth 4))
    [Console]::Out.Flush()
}

try {
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
    Send @{ event = 'ready'; voices = $voices }
} catch {
    Send @{ event = 'error'; error = $_.Exception.Message }
    exit 1
}

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $id = $null
    try {
        $request = $line | ConvertFrom-Json
        $id = $request.id
        if ($request.cmd -eq 'say') {
            if ($request.voice) { $synth.SelectVoice([string]$request.voice) }
            $synth.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$request.rate))
            $stream = New-Object System.IO.MemoryStream
            $synth.SetOutputToAudioStream($stream, $format)
            $synth.Speak([string]$request.text)
            $synth.SetOutputToNull()
            Send @{ event = 'audio'; id = $id; pcm = [Convert]::ToBase64String($stream.ToArray()) }
        } elseif ($request.cmd -eq 'listen_setup') {
            if ($null -ne $listener) { $listener.Dispose() }
            $listener = New-Object PaddockListener -ArgumentList (,[string[]]$request.phrases)
            Send @{ event = 'listen_ready'; id = $id }
        } elseif ($request.cmd -eq 'listen_start') {
            $listener.Start()
            Send @{ event = 'listening'; id = $id }
        } elseif ($request.cmd -eq 'listen_stop') {
            $listener.Stop(1500)
            Send @{ event = 'heard'; id = $id; text = $listener.Text; confidence = $listener.Confidence; detected_speech = $listener.DetectedSpeech; problem = $listener.Error }
        } else {
            Send @{ event = 'error'; id = $id; error = 'Unknown request.' }
        }
    } catch {
        Send @{ event = 'error'; id = $id; error = $_.Exception.Message }
    }
}
if ($null -ne $listener) { $listener.Dispose() }
$synth.Dispose()
