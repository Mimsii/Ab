import sysconfig

python = f"python{sysconfig.get_config_var('VERSION')}"
nodot = sysconfig.get_config_var("py_version_nodot")
base = "/opt/venvs/securedrop-app-code"
text = f"""\
LoadModule wsgi_module "/opt/venvs/securedrop-app-code/lib/{python}/site-packages/mod_wsgi/server/mod_wsgi-py{nodot}{sysconfig.get_config_var('EXT_SUFFIX')}"
WSGIPythonHome "/opt/venvs/securedrop-app-code"
"""  # noqa: E501

print(text.strip())
