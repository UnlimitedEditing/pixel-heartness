-- Cutout rig for Delver-style character sprites. Run headless:
--   Aseprite.exe -b --script-param rig=<rig.json> --script-param mode=<slice|build> --script pixelanim/rig.lua
--
-- Aseprite has no bones and no arbitrary-angle rotate in the Lua API, so every part
-- transform is done here: one inverse-mapped nearest-neighbour pass per part per frame.
-- One pass means no resampling accumulation, which is the whole game at 44 texels tall.

local function fail(msg) error("rig.lua: " .. msg, 0) end

local rigPath = app.params["rig"] or fail("missing --script-param rig=<path>")
local mode = app.params["mode"] or "build"

local f = io.open(rigPath, "r") or fail("cannot open rig " .. rigPath)
local rig = json.decode(f:read("a"))
f:close()

-- relative paths in the rig file are relative to the rig file, as in riglib.py
local rigDir = rigPath:gsub("\\", "/"):match("^(.*)/[^/]*$") or "."
for _, key in ipairs({"source", "parts_file", "anim_file", "strip_file", "ase_strip_file", "parts_dir"}) do
  local v = rig[key]
  if v and not (v:match("^%a:[/" .. string.char(92) .. "]") or v:sub(1, 1) == "/") then rig[key] = rigDir .. "/" .. v end
end

-- rig.lua's own strip; never strip_file, which render.py owns (see checks.py agree)
local aseStrip = rig.ase_strip_file or rig.strip_file:gsub("%.png$", "_ase.png")

local CW, CH = rig.cell[1], rig.cell[2]

-- variant art paths are relative to the rig file too
for _, p in ipairs(rig.parts) do
  for v, f in pairs(p.variants or {}) do
    if not (f:match("^%a:[/" .. string.char(92) .. "]") or f:sub(1, 1) == "/") then
      p.variants[v] = rigDir .. "/" .. f
    end
  end
end

-- ---------------------------------------------------------------- matrices
-- 2x3 affine {a,b,c,d,e,f} mapping (x,y) -> (a*x + c*y + e, b*x + d*y + f)
local function mid() return {1, 0, 0, 1, 0, 0} end

local function mmul(m, n) -- apply n first, then m
  return {
    m[1] * n[1] + m[3] * n[2],
    m[2] * n[1] + m[4] * n[2],
    m[1] * n[3] + m[3] * n[4],
    m[2] * n[3] + m[4] * n[4],
    m[1] * n[5] + m[3] * n[6] + m[5],
    m[2] * n[5] + m[4] * n[6] + m[6],
  }
end

local function minv(m)
  local det = m[1] * m[4] - m[2] * m[3]
  if math.abs(det) < 1e-9 then return nil end
  local ia, ib, ic, id = m[4] / det, -m[2] / det, -m[3] / det, m[1] / det
  return {ia, ib, ic, id, -(ia * m[5] + ic * m[6]), -(ib * m[5] + id * m[6])}
end

local function mapply(m, x, y)
  return m[1] * x + m[3] * y + m[5], m[2] * x + m[4] * y + m[6]
end

-- pose -> matrix, applied about the part pivot in cell coords
local function poseMatrix(pose, px, py)
  local rot = math.rad(pose.rot or 0)
  local sx, sy = pose.sx or 1, pose.sy or 1
  local co, si = math.cos(rot), math.sin(rot)
  local r = {co * sx, si * sx, -si * sy, co * sy, 0, 0}
  -- translate(pivot + d) . R . translate(-pivot)
  local t1 = {1, 0, 0, 1, -px, -py}
  local t2 = {1, 0, 0, 1, px + (pose.dx or 0), py + (pose.dy or 0)}
  return mmul(t2, mmul(r, t1))
end

-- ---------------------------------------------------------------- parts
local partByName = {}
for _, p in ipairs(rig.parts) do partByName[p.name] = p end

local function worldMatrix(part, pose, cache)
  if cache[part.name] then return cache[part.name] end
  local m = poseMatrix(pose[part.name] or {}, part.pivot[1], part.pivot[2])
  if part.parent then
    local pp = partByName[part.parent] or fail("unknown parent " .. part.parent)
    m = mmul(worldMatrix(pp, pose, cache), m)
  end
  cache[part.name] = m
  return m
end

-- ---------------------------------------------------------------- parts dir
-- Where segment.py writes its layers. Defaults beside the parts file.
local function partsDir()
  if rig.parts_dir then return rig.parts_dir end
  return (rig.parts_file:gsub("%.aseprite$", ""))
end

-- ---------------------------------------------------------------- import mode
-- Build the hand-editable parts file from segment.py's output. This replaces the
-- old `slice` mode, which cut parts with plain rectangles and so sliced through
-- neighbouring bones. segment.py cuts along colour edges and, crucially, extends
-- each part under the parts drawn in front of it, so a limb has art to reveal
-- when it swings. Hand edits here still survive: `build` reads this file, not the
-- PNGs.
if mode == "import" or mode == "slice" then
  if mode == "slice" then
    print("note: `slice` is superseded by segment.py; importing its output instead")
  end
  local dir = partsDir()
  local mf = io.open(dir .. "/manifest.json", "r")
      or fail("no segmented parts at " .. dir .. " -- run Tools/anim/segment.py first")
  local man = json.decode(mf:read("a"))
  mf:close()

  local out = Sprite(CW, CH, ColorMode.RGB)
  out:deleteLayer(out.layers[1])
  for _, e in ipairs(man.parts) do -- manifest is in rig order: backmost first
    local img = app.open(dir .. "/" .. e.layer) or fail("cannot open " .. e.layer)
    local flat = Image(CW, CH, ColorMode.RGB)
    flat:drawSprite(img, 1)
    local layer = out:newLayer()
    layer.name = e.name
    out:newCel(layer, 1, flat, Point(0, 0))
  end
  out:saveAs(rig.parts_file)
  -- record which segmentation this file came from, so `build` can refuse to mix
  -- fresh provenance masks with stale part pixels -- a silent 43-texel drift
  local st = io.open(rig.parts_file .. ".stamp", "w")
  st:write(man.stamp or "")
  st:close()
  print(string.format("imported %d parts from %s -> %s", #man.parts, dir, rig.parts_file))
  return
end

-- ---------------------------------------------------------------- build mode
local parts = app.open(rig.parts_file) or fail("no parts file, run mode=import first: " .. rig.parts_file)

-- read each part's authored pixels straight off its layer
local srcOf = {}
for _, layer in ipairs(parts.layers) do
  local cel = layer:cel(1)
  if cel then
    srcOf[layer.name] = {img = cel.image, ox = cel.position.x, oy = cel.position.y}
  end
end
for _, p in ipairs(rig.parts) do
  if not srcOf[p.name] then fail("parts file has no layer named '" .. p.name .. "'") end
end

-- Part variants: authored alternate art, swapped per frame by pose[part].variant.
-- A full-size sprite placed by the same rule as the source (centred, bottom
-- aligned), with no synthesised texels. Mirrors render.py's Parts.
for _, p in ipairs(rig.parts) do
  for v, f in pairs(p.variants or {}) do
    local sp = app.open(f) or fail("cannot open variant " .. f)
    local flat = Image(sp.width, sp.height, ColorMode.RGB)
    flat:drawSprite(sp, 1)
    srcOf[p.name .. "@" .. v] = {img = flat, ox = math.floor((CW - sp.width) / 2),
                                 oy = CH - sp.height, variant = true}
  end
end

do  -- the parts file and the provenance masks must come from the same segment.py run
  local mf = io.open(partsDir() .. "/manifest.json", "r")
  if mf then
    local want = json.decode(mf:read("a")).stamp
    mf:close()
    local sf = io.open(rig.parts_file .. ".stamp", "r")
    local got = sf and sf:read("a") or nil
    if sf then sf:close() end
    if want and got ~= want then
      fail("parts file is from a different segment.py run than " .. partsDir()
           .. " -- re-run with --script-param mode=import first")
    end
  end
end

-- provenance: which texels segment.py invented. Read from the parts dir rather
-- than the parts file, so a texel the artist paints by hand counts as authored
-- and can anchor its part's underlap -- which is the conservative direction.
local synthOf = {}
for _, p in ipairs(rig.parts) do
  local path = partsDir() .. "/" .. p.name .. ".synth.png"
  local m = {}
  if app.fs.isFile(path) then
    local s = app.open(path)
    local flat = Image(CW, CH, ColorMode.RGB)
    flat:drawSprite(s, 1)
    for y = 0, CH - 1 do
      m[y] = {}
      for x = 0, CW - 1 do
        m[y][x] = app.pixelColor.rgbaA(flat:getPixel(x, y)) > 127
      end
    end
  end
  synthOf[p.name] = m
end

-- Lag and squash. Mirrors riglib.resolve_state / squash_matrix, and must agree
-- with them texel for texel (the `agree` gate). See the docstring there for why
-- lag steps once per key frame and sums parent rotations rather than composing.
local MAX_LAG = 0.95

local fkOrder, fkSeen = {}, {}
local function fkVisit(p)
  if fkSeen[p.name] then return end
  fkSeen[p.name] = true
  if p.parent then fkVisit(partByName[p.parent]) end
  fkOrder[#fkOrder + 1] = p
end
for _, p in ipairs(rig.parts) do fkVisit(p) end

local hasLag = false
for _, p in ipairs(rig.parts) do if p.lag and p.lag ~= 0 then hasLag = true end end

local function resolveState(st)
  local passes = (st.loop ~= false and hasLag) and 3 or 1
  local L, resolved = {}, {}
  for _ = 1, passes do
    resolved = {}
    for _, fr in ipairs(st.frames) do
      local pose = {}
      for n, v in pairs(fr.pose or {}) do
        local c = {}
        for k, x in pairs(v) do c[k] = x end
        pose[n] = c
      end
      local eff = {}
      for _, p in ipairs(fkOrder) do
        local own = (pose[p.name] and pose[p.name].rot) or 0
        if p.lag and p.lag ~= 0 then
          local lag = math.min(MAX_LAG, math.max(0, p.lag))
          local pw, cur = 0, p.parent
          while cur do
            pw = pw + eff[cur]
            cur = partByName[cur].parent
          end
          if L[p.name] == nil then L[p.name] = pw end
          L[p.name] = pw - lag * (pw - L[p.name])
          local extra = L[p.name] - pw
          if extra ~= 0 then
            pose[p.name] = pose[p.name] or {}
            pose[p.name].rot = own + extra
          end
          own = own + extra
        end
        eff[p.name] = own
      end
      resolved[#resolved + 1] = {pose = pose, squash = fr.squash or 0}
    end
  end
  return resolved
end

local rootPart = rig.parts[1]
for _, p in ipairs(rig.parts) do if not p.parent then rootPart = p break end end
local squashBase = rig.squash_base or {rig.symmetry_x or rootPart.pivot[1], CH - 1}

local function squashMatrix(amount)
  if amount == 0 then return {1, 0, 0, 1, 0, 0} end
  local sy = 1 - amount
  local sx = 1 / sy
  return {sx, 0, 0, sy, squashBase[1] - sx * squashBase[1], squashBase[2] - sy * squashBase[2]}
end

-- flatten states into a frame list
local frames, tags = {}, {}
for _, st in ipairs(rig.states) do
  local from = #frames + 1
  local res = resolveState(st)
  for i, fr in ipairs(st.frames) do
    frames[#frames + 1] = {pose = res[i].pose, squash = res[i].squash, state = st.name,
                           ms = math.floor(1000 / (st.fps or 8) * (fr.hold or 1))}
  end
  tags[#tags + 1] = {name = st.name, from = from, to = #frames, loop = st.loop ~= false}
end

local out = Sprite(CW, CH, ColorMode.RGB)
while #out.frames < #frames do out:newFrame() end
out:deleteLayer(out.layers[1])

-- render one part into one frame, inverse-mapped over its destination bbox.
-- gdx/gdy post-translate every part by whole texels; ground lock uses them, and
-- they are applied inside the matrix (not by moving cels afterwards) so that
-- clipping to the cell happens after the shift, exactly as render.py does it.
local gdx, gdy = 0, 0
local gsq = {1, 0, 0, 1, 0, 0} -- this frame's squash, applied after FK and before the shift
local function renderPart(p, pose)
  local vname = pose[p.name] and pose[p.name].variant
  local s = srcOf[vname and (p.name .. "@" .. vname) or p.name]
    or fail("part " .. p.name .. " has no variant '" .. tostring(vname) .. "'")
  local m = mmul({1, 0, 0, 1, gdx, gdy}, mmul(gsq, worldMatrix(p, pose, {})))
  local inv = minv(m)
  if not inv then return nil, 0, 0 end

  local w, h = s.img.width, s.img.height
  local minx, miny, maxx, maxy = math.huge, math.huge, -math.huge, -math.huge
  for _, c in ipairs({{s.ox, s.oy}, {s.ox + w, s.oy}, {s.ox, s.oy + h}, {s.ox + w, s.oy + h}}) do
    local X, Y = mapply(m, c[1], c[2])
    minx, maxx = math.min(minx, X), math.max(maxx, X)
    miny, maxy = math.min(miny, Y), math.max(maxy, Y)
  end
  minx, miny = math.max(0, math.floor(minx)), math.max(0, math.floor(miny))
  maxx, maxy = math.min(CW - 1, math.ceil(maxx)), math.min(CH - 1, math.ceil(maxy))
  if minx > maxx or miny > maxy then return nil, 0, 0 end

  local dst = Image(maxx - minx + 1, maxy - miny + 1, ColorMode.RGB)
  local syn, sm = {}, (not s.variant) and synthOf[p.name] or nil
  for Y = miny, maxy do
    syn[Y - miny] = {}
    for X = minx, maxx do
      local u, v = mapply(inv, X + 0.5, Y + 0.5)
      local su, sv = math.floor(u), math.floor(v)
      local sx, sy = su - s.ox, sv - s.oy
      if sx >= 0 and sx < w and sy >= 0 and sy < h then
        local c = s.img:getPixel(sx, sy)
        if app.pixelColor.rgbaA(c) > 127 then -- binary alpha, per ART_SPEC
          dst:putPixel(X - minx, Y - miny, c)
          -- the synth mask is cell-sized with origin 0, so it indexes by the
          -- untranslated source coordinate
          if sm and sm[sv] and sm[sv][su] then syn[Y - miny][X - minx] = true end
        end
      end
    end
  end
  return dst, minx, miny, syn
end

local layerOf = {}
for _, p in ipairs(rig.parts) do -- z order = rig.parts order, backmost first
  local l = out:newLayer()
  l.name = p.name
  layerOf[p.name] = l
end

-- Drop any visible component of a part made only of invented texels. Underlap is
-- meant to be revealed attached to the art it extends; a patch that surfaces with
-- no authored texel of its own part beside it is a stray, and it reads as one --
-- it does not move with anything, because the part it belongs to is elsewhere.
-- Must stay identical to render.py's cull, or the `agree` gate fails.
local function cullFloaters(R)
  for _ = 1, 4 do
    local owner, syn = {}, {}
    for y = 0, CH - 1 do owner[y] = {}; syn[y] = {} end
    for ri, r in ipairs(R) do
      for yy = 0, r.img.height - 1 do
        for xx = 0, r.img.width - 1 do
          local X, Y = r.x + xx, r.y + yy
          if X >= 0 and X < CW and Y >= 0 and Y < CH
             and app.pixelColor.rgbaA(r.img:getPixel(xx, yy)) > 127 then
            owner[Y][X] = ri
            syn[Y][X] = r.syn[yy] and r.syn[yy][xx] or false
          end
        end
      end
    end

    local seen, dropped = {}, false
    for y = 0, CH - 1 do seen[y] = {} end
    for y = 0, CH - 1 do
      for x = 0, CW - 1 do
        if owner[y][x] and not seen[y][x] then
          local ri = owner[y][x]
          local stack, comp, anchored = {{x, y}}, {}, false
          seen[y][x] = true
          while #stack > 0 do
            local c = table.remove(stack)
            comp[#comp + 1] = c
            if not syn[c[2]][c[1]] then anchored = true end
            for dy = -1, 1 do
              for dx = -1, 1 do
                local nx, ny = c[1] + dx, c[2] + dy
                if nx >= 0 and nx < CW and ny >= 0 and ny < CH
                   and not seen[ny][nx] and owner[ny][nx] == ri then
                  seen[ny][nx] = true
                  stack[#stack + 1] = {nx, ny}
                end
              end
            end
          end
          if not anchored then
            local r = R[ri]
            for _, c in ipairs(comp) do
              r.img:putPixel(c[1] - r.x, c[2] - r.y, app.pixelColor.rgba(0, 0, 0, 0))
            end
            dropped = true
          end
        end
      end
    end
    if not dropped then return end
  end
end

-- Ground lock: rotating a limb about a joint above it moves its far end down by
-- x*sin(t) + y*(cos(t)-1), and for a foot that sits sideways of the hip the first
-- term dominates -- so "pair any leg rot with dy:-1" is necessary but wrong by a
-- texel depending on which way the leg swings. Solve it instead of advising it:
-- render once to find the lowest texel, then re-render the whole frame shifted so
-- it lands on the floor row. Must stay identical to render.py's ground_lock().
local groundLock = rig.ground_lock ~= false
local airborne = {}
for _, s in ipairs(rig.airborne_states or {}) do airborne[s] = true end
local floorRow = CH - 2

local function renderFrame(fr)
  local R = {}
  for _, p in ipairs(rig.parts) do -- backmost first, so index order is z order
    local img, x, y, syn = renderPart(p, fr.pose)
    if img then R[#R + 1] = {name = p.name, img = img, x = x, y = y, syn = syn} end
  end
  cullFloaters(R)
  return R
end

-- Measured on the culled frame, because render.py measures it on the culled
-- frame: a stray that is about to be dropped must not decide where the floor is.
local function lowestRow(fr)
  local low = -1
  for _, r in ipairs(renderFrame(fr)) do
    for yy = r.img.height - 1, 0, -1 do
      local any = false
      for xx = 0, r.img.width - 1 do
        if app.pixelColor.rgbaA(r.img:getPixel(xx, yy)) > 127 then any = true break end
      end
      if any then
        if r.y + yy > low then low = r.y + yy end
        break
      end
    end
  end
  return low
end

for i, fr in ipairs(frames) do
  gdx, gdy = 0, 0
  gsq = squashMatrix(fr.squash)
  if groundLock and not airborne[fr.state] then
    local low = lowestRow(fr)
    if low >= 0 then gdy = floorRow - low end
  end
  for _, r in ipairs(renderFrame(fr)) do
    out:newCel(layerOf[r.name], i, r.img, Point(r.x, r.y))
  end
end
gdx, gdy = 0, 0
gsq = {1, 0, 0, 1, 0, 0}

-- carry hand touch-ups across rebuilds: any layer named with a leading '+'
local prev = nil
if app.fs.isFile(rig.anim_file) then prev = app.open(rig.anim_file) end
if prev then
  for _, layer in ipairs(prev.layers) do
    if layer.name:sub(1, 1) == "+" then
      local keep = out:newLayer()
      keep.name = layer.name
      for i = 1, math.min(#frames, #prev.frames) do
        local cel = layer:cel(i)
        if cel then out:newCel(keep, i, cel.image, cel.position) end
      end
    end
  end
end

for i, fr in ipairs(frames) do out.frames[i].duration = fr.ms / 1000.0 end
for _, t in ipairs(tags) do
  local tag = out:newTag(t.from, t.to)
  tag.name = t.name
  tag.aniDir = t.loop and AniDir.FORWARD or AniDir.FORWARD
end

out:saveAs(rig.anim_file)

-- horizontal strip, one row, frames left to right (ART_SPEC animation layout)
app.command.ExportSpriteSheet{
  ui = false,
  type = SpriteSheetType.HORIZONTAL,
  textureFilename = aseStrip,
  dataFilename = aseStrip:gsub("%.png$", ".json"),
  dataFormat = SpriteSheetDataFormat.JSON_ARRAY,
  listTags = true,
  trim = false,
}

print(string.format("built %d frames across %d states -> %s", #frames, #tags, aseStrip))
for _, t in ipairs(tags) do
  print(string.format("  %-10s frames %d-%d", t.name, t.from, t.to))
end
