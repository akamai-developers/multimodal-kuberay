## Vision-to-Voice Client

This folder contains the Python code that captures webcam frames, calls the Ray Serve multimodal endpoint, and plays the returned audio on the laptop speakers.

### Quick start

1. Create a virtual environment with Python 3.10+ and install the package:
	```sh
	cd device
	pip install -e .
	```
2. Export the endpoint details that the Ray cluster exposes (skip this for `--offline` dry runs):
	```sh
	export VISION_VOICE_URL="http://<gateway-ip>/vision-voice/analyze"
	export VISION_VOICE_TOKEN="${OPEN_API_KEY}"
	```
3. Run the client:
	```sh
	python -m device_app --log-level=INFO
	```

### Offline front-end test

To verify camera access and speaker playback before the Ray backend is ready, add `--offline`. This skips network calls, feeds frames into a stub client, and plays a short sine-wave clip for each detected motion event:

	```sh
	python -m device_app --offline --log-level=DEBUG
	```

The client downsamples the webcam stream, sends motion-triggered frames to the cluster, and plays the synthesized fun-fact audio responses.

During both online and offline runs an OpenCV window labeled **VisionVoice** mirrors the current frame, overlays the detected torso bounding boxes, and only forwards frames that include a confident T-shirt detection to the backend.


IMG=$(base64 < 1.jpg | tr -d '\n')

curl -X POST http://172.233.212.213:11434/api/chat \
-H "Content-Type: application/json" \
-d '{
    "model": "qwen3-vl:8b",
    "messages": [{
        "role": "user",
        "content": "You are a Tech brand logo/name identification expert. Look at all the brands in this image and identify all the tech brand logos visible. Reply with ONLY the brand name and  one liner about the brand nothing else. If you cannot identify a brand, reply with 'Unknown'.",
        "images": ["'"$IMG"'"]
    }],
    "stream": false
}' | jq -r .message.content
```sh
for i in {1..15}; do
    IMG=$(base64 < $i.jpg | tr -d '\n')
    
    curl -X POST http://172.233.212.213:11434/api/chat \
    -H "Content-Type: application/json" \
    -d '{
        "model": "qwen3-vl:8b",
        "messages": [{
            "role": "user",
            "content": "You are a Tech brand logo/name identification expert. Look at all the brands in this image and identify all the tech brand logos visible. Reply with ONLY the brand name and one liner about the brand nothing else. If you cannot identify a brand, reply with '"'"'Unknown'"'"'.",
            "images": ["'"$IMG"'"]
        }],
        "stream": false
    }' | jq -r .message.content
done
```
