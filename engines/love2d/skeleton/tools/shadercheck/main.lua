-- ---------------------------------------------------------------------------
-- tools/shadercheck/main.lua
-- Purpose : Compiles (and with --render draws) the kit's shader recipes, shaders/kit/*.glsl, with LÖVE itself:
--             lovec tools/shadercheck <project root>            compile every recipe (dev.py check)
--             lovec tools/shadercheck <project root> --render   also draw each into a 64x64 canvas (smoke --shaders)
-- Notes   : Prints "SHADER_OK <name>" or "SHADER_FAIL <name> <message>" per recipe, with --render also
--           "SHADER_PNG <name> <base64 PNG>", then "SHADER_CHECK_DONE <recipes> <failed>". dev.py writes the
--           pictures to build/shader_check/ and tools/shaders/shader_ref.py compares them with the golden images.
--           The pictures go out on stdout, so this program never writes a file. Files are read by absolute path
--           (love.filesystem only sees this checker's folder), through _wfopen on Windows for non-ASCII project
--           paths, as tools/lovecheck does.
--           Pseudocode
--             params = load shaders/kit/params.lua; for each recipe in it:
--               newShader(the .glsl) under pcall -> SHADER_FAIL on an error
--               --render: main input drawn nearest-neighbour onto a 64x64 canvas (blend "replace", premultiplied:
--               the shader's output is written as is), every parameter and the aux picture sent -> PNG -> base64
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------

-- ---- Tunables ----------------------------------------------------------------
local SIZE = 64                            -- the check canvas (tools/shaders/recipes.json)
local SHADER_DIR = "shaders/kit"
local INPUT_DIR = "data/shaders/inputs"
local WIN_UTF8 = 65001
local WIN_INVALID_CHARS = 8
local READ_CHUNK = 65536

local ok_ffi, ffi = pcall(require, "ffi")
local WIDE = ok_ffi and ffi.os == "Windows"
if WIDE then
  for _, decl in ipairs({
    "int MultiByteToWideChar(unsigned int cp, unsigned long flags, const char *src, int srclen, uint16_t *dst, "
      .. "int dstlen);",
    "void *_wfopen(const uint16_t *name, const uint16_t *mode);",
    "size_t fread(void *buf, size_t size, size_t n, void *f);",
    "int fclose(void *f);",
  }) do pcall(ffi.cdef, decl) end
end

local function wide(s)
  local n = ffi.C.MultiByteToWideChar(WIN_UTF8, WIN_INVALID_CHARS, s, -1, nil, 0)
  if n == 0 then return nil end
  local buf = ffi.new("uint16_t[?]", n)
  if ffi.C.MultiByteToWideChar(WIN_UTF8, WIN_INVALID_CHARS, s, -1, buf, n) == 0 then return nil end
  return buf
end

-- The file's bytes, or nil when it cannot be opened
local function read_file(path)
  local wpath = WIDE and wide(path)
  if not wpath then
    local f = io.open(path, "rb")
    if not f then return nil end
    local data = f:read("*a")
    f:close()
    return data
  end
  local f = ffi.C._wfopen(wpath, wide("rb"))
  if f == nil then return nil end
  local buf, parts = ffi.new("char[?]", READ_CHUNK), {}
  while true do
    local got = tonumber(ffi.C.fread(buf, 1, READ_CHUNK, f))
    if got > 0 then parts[#parts + 1] = ffi.string(buf, got) end
    if got < READ_CHUNK then break end
  end
  ffi.C.fclose(f)
  return table.concat(parts)
end

local function fail_env(msg)
  io.stderr:write("[error] " .. msg .. "\n")
  io.stderr:flush()
  os.exit(2)
end

-- An input picture as a nearest-filtered Image ("sphere" is the sphere's normal map)
local function input(root, name)
  local file = (name == "sphere" and "sphere_normal" or name) .. ".png"
  local bytes = read_file(root .. "/" .. INPUT_DIR .. "/" .. file)
  if not bytes then fail_env("cannot read " .. INPUT_DIR .. "/" .. file) end
  local img = love.graphics.newImage(love.image.newImageData(love.filesystem.newFileData(bytes, file)))
  img:setFilter("nearest", "nearest")
  return img
end

local function send(shader, name, value)
  if shader:hasUniform(name) then shader:send(name, value) end   -- the compiler drops unused uniforms
end

local function render(root, shader, recipe)
  local main = input(root, recipe.main)
  local canvas = love.graphics.newCanvas(SIZE, SIZE)
  for k, v in pairs(recipe.params) do send(shader, "u_" .. k, v) end
  if recipe.aux then send(shader, "kit_aux", input(root, recipe.aux)) end
  love.graphics.setCanvas(canvas)
  love.graphics.clear(0, 0, 0, 0)
  love.graphics.setBlendMode("replace", "premultiplied")
  love.graphics.setColor(1, 1, 1, 1)
  love.graphics.setShader(shader)
  love.graphics.draw(main, 0, 0, 0, SIZE / main:getWidth(), SIZE / main:getHeight())
  love.graphics.setShader()
  love.graphics.setCanvas()
  local png = canvas:newImageData():encode("png"):getString()
  return love.data.encode("string", "base64", png)
end

function love.load(args)
  local root, draw = nil, false
  for _, a in ipairs(args or {}) do
    if a == "--render" then draw = true elseif not root then root = a end
  end
  if not root then fail_env("usage: lovec tools/shadercheck <project root> [--render]") end
  root = root:gsub("[/\\]+$", "")
  local src = read_file(root .. "/" .. SHADER_DIR .. "/params.lua")
  if not src then fail_env("no " .. SHADER_DIR .. "/params.lua: python tools/shaders/shader_gen.py writes it") end
  local chunk, err = loadstring(src, "@params.lua")
  if not chunk then fail_env("params.lua: " .. err) end
  local recipes = chunk()
  local names = {}
  for name in pairs(recipes) do names[#names + 1] = name end
  table.sort(names)
  local failed = 0
  for _, name in ipairs(names) do
    local code = read_file(root .. "/" .. SHADER_DIR .. "/" .. name .. ".glsl")
    local ok, shader = false, "cannot read the file"
    if code then ok, shader = pcall(love.graphics.newShader, code) end
    if not ok then
      failed = failed + 1
      print("SHADER_FAIL " .. name .. " " .. tostring(shader):gsub("\n", " | "))
    else
      print("SHADER_OK " .. name)
      if draw then
        local okr, png = pcall(render, root, shader, recipes[name])
        if okr then
          print("SHADER_PNG " .. name .. " " .. png)
        else
          failed = failed + 1
          print("SHADER_FAIL " .. name .. " " .. tostring(png):gsub("\n", " | "))
        end
      end
    end
  end
  print(string.format("SHADER_CHECK_DONE %d %d", #names, failed))
  io.stdout:flush()
  os.exit(failed > 0 and 1 or 0)
end
