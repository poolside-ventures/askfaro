"""askfaro quickstart.

    pip install askfaro
    python examples/quickstart.py

Free tools run on-device — no API key, no network, no credits. Pass an api_key
(or set FARO_API_KEY) to also reach vendor-backed tools through the Faro backend.
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
