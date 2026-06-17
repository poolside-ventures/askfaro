"""askfaro quickstart.

    pip install askfaro
    python examples/quickstart.py

Free tools run on-device, with no API key, no network, no credits. Pass an api_key
(or set FARO_API_KEY) to also reach vendor-backed tools through the Faro backend.
Discovery (search/browse) also needs no key.
"""

from faro import Faro

faro = Faro()  # no key needed for on-device tools

# Exact arithmetic (the model shouldn't eyeball this).
r = faro.invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
print("calc:", r.data["result"], "(ran locally:", r.local, ")")

# Unit conversion against a real dimensional registry.
r = faro.invoke("units/convert", {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"})
print("units:", r.data["result"], r.data.get("to_unit", ""))

# Phone parsing/validation via libphonenumber metadata.
r = faro.invoke("phone/parse", {"number": "+14155552671"})
print("phone:", r.data["e164"], "|", r.data["region_code"], "|", r.data["number_type"])

# What can run on-device in this build?
print("on-device tools:", ", ".join(sorted(faro.local_namespaces())))

# Discovery: describe what you want, get suitable skills back (no key needed).
# This one calls the live catalog, so it needs network.
try:
    hits = faro.search("transcribe an audio file", limit=3)
    print("search:", ", ".join(h.id for h in hits) or "(no matches)")
except Exception as e:  # offline / no network
    print("search: skipped:", e)

# Run a skill (any vendor-backed capability). Needs an API key and a skill-agent
# URL; the agent picks the tools, runs them, and bills your account:
#   faro = Faro(api_key="faro_...", skill_url="https://<your-skill-agent>")
#   r = faro.run("image", {"prompt": "a red bicycle"})
#   print(r.status, r.data)
