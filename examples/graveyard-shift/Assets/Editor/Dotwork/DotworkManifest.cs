// ---------------------------------------------------------------------------
// DotworkManifest.cs
// Purpose : Reading a Dotwork asset manifest (<assets_dir>/dotwork/<pack>.assets.json, spec in
//           tools/art/dotwork/ASSET_MANIFEST.md): the header check (format, major version), path resolution
//           (join(dirname(manifest), base, path), inside Assets/), PNG sizes from the file header, and small
//           typed accessors over Core/Json's value tree. The importer and the verify check share it.
// Usage   : var m = DotworkManifest.Load("Assets/dotwork/town.assets.json");   // DotworkImportException on a bad file
//           string asset = m.Resolve("art/props/spr_crate.png");                 // Assets/art/props/spr_crate.png
//           Vector2Int size = DotworkManifest.PngSize(asset);
// Notes   : Asset paths are Unity's (forward slashes, starting at Assets). The spec forbids "..", a drive and a
//           leading "/" in a path; a manifest whose base leaves Assets/ is refused, because Unity imports only
//           what is under Assets/. Another major version is refused with both versions named; within major 1
//           unknown fields are ignored (the importer skips unknown kinds with a warning).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using graveyard_shift.Core;

namespace graveyard_shift.Dotwork
{
    /// <summary>A problem with a manifest or its files: dev.py exec exits 1 with this message.</summary>
    public sealed class DotworkImportException : Exception
    {
        public DotworkImportException(string message) : base(message) { }
    }

    public sealed class DotworkManifest
    {
        // ---- Tunables ------------------------------------------------------------
        public const string FORMAT = "dotwork-assets";
        public const int SUPPORTED_MAJOR = 1;                // reads every 1.x manifest
        public const string SUFFIX = ".assets.json";
        public const string FOLDER = "Assets/dotwork";       // where Dotwork writes a Unity game's manifests
        public static readonly string[] CORE_KINDS =
            { "animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font", "ui_kit" };
        public static readonly string[] EXTRA_KINDS = { "background", "particles", "transition", "normal_map", "image" };

        public string Path { get; private set; }             // the manifest's asset path
        public string Text { get; private set; }
        public string Hash { get; private set; }             // SHA-256 of the file bytes, hex
        public Dictionary<string, object> Doc { get; private set; }
        public string Pack => Str(Doc, "pack", "");
        public string Version => Str(Doc, "version", "");
        public string Base { get; private set; }             // asset path of the folder every path is relative to
        public List<Dictionary<string, object>> Assets { get; } = new List<Dictionary<string, object>>();

        public static DotworkManifest Load(string assetPath)
        {
            string full = System.IO.Path.GetFullPath(assetPath);
            if (!File.Exists(full))
            {
                throw new DotworkImportException($"{assetPath} not found");
            }
            byte[] bytes = File.ReadAllBytes(full);
            var m = new DotworkManifest { Path = Norm(assetPath), Text = Encoding.UTF8.GetString(bytes) };
            using (SHA256 sha = SHA256.Create())
            {
                m.Hash = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
            }
            object root;
            try
            {
                root = Json.Parse(m.Text.TrimStart('﻿'));
            }
            catch (FormatException e)
            {
                throw new DotworkImportException($"{assetPath} is not valid JSON: {e.Message}");
            }
            m.Doc = root as Dictionary<string, object>;
            if (m.Doc == null || Str(m.Doc, "format", "") != FORMAT)
            {
                throw new DotworkImportException($"{assetPath} is not a Dotwork asset manifest (format must be \"{FORMAT}\")");
            }
            int major = Major(m.Version);
            if (major != SUPPORTED_MAJOR)
            {
                throw new DotworkImportException($"{assetPath} has manifest version {m.Version}, major {major}; this importer reads " +
                                                 $"major {SUPPORTED_MAJOR} ({SUPPORTED_MAJOR}.x). Update the kit's importer or re-run Dotwork.");
            }
            m.Base = Norm(DirOf(m.Path) + "/" + Str(m.Doc, "base", "."));
            if (m.Base != "Assets" && !m.Base.StartsWith("Assets/", StringComparison.Ordinal))
            {
                throw new DotworkImportException($"{assetPath}: base \"{Str(m.Doc, "base", ".")}\" leaves Assets/ ({m.Base}); " +
                                                 "Unity imports only files under Assets/");
            }
            foreach (object a in List(m.Doc, "assets"))
            {
                if (a is Dictionary<string, object> d)
                {
                    m.Assets.Add(d);
                }
            }
            return m;
        }

        /// <summary>Every manifest of the game: Assets/dotwork/*.assets.json, sorted.</summary>
        public static List<string> FindAll(string folder = FOLDER)
        {
            var found = new List<string>();
            if (Directory.Exists(folder))
            {
                foreach (string f in Directory.GetFiles(folder, "*" + SUFFIX, SearchOption.TopDirectoryOnly))
                {
                    found.Add(Norm(f));
                }
            }
            found.Sort(StringComparer.Ordinal);
            return found;
        }

        /// <summary>The asset path of a manifest path; throws on a path the spec forbids.</summary>
        public string Resolve(string rel)
        {
            if (string.IsNullOrEmpty(rel) || rel.StartsWith("/", StringComparison.Ordinal) || rel.Contains("\\")
                || rel.Contains(":") || Array.IndexOf(rel.Split('/'), "..") >= 0)
            {
                throw new DotworkImportException($"{Path}: path \"{rel}\" is not allowed (relative, forward slashes, no \"..\")");
            }
            return Norm(Base + "/" + rel);
        }

        /// <summary>The path relative to the manifest's base (the manifest's own spelling), for reports.</summary>
        public string Relative(string assetPath)
        {
            string b = Base + "/";
            return assetPath.StartsWith(b, StringComparison.Ordinal) ? assetPath.Substring(b.Length) : assetPath;
        }

        /// <summary>(width, height) from a PNG's IHDR chunk, without decoding it; null when it is no PNG.</summary>
        public static Vector2Int? PngSize(string assetPath)
        {
            string full = System.IO.Path.GetFullPath(assetPath);
            if (!File.Exists(full))
            {
                return null;
            }
            var head = new byte[24];
            using (FileStream f = File.OpenRead(full))
            {
                if (f.Read(head, 0, 24) < 24)
                {
                    return null;
                }
            }
            byte[] sig = { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
            for (int i = 0; i < 8; i++)
            {
                if (head[i] != sig[i])
                {
                    return null;
                }
            }
            if (head[12] != 'I' || head[13] != 'H' || head[14] != 'D' || head[15] != 'R')
            {
                return null;
            }
            int w = (head[16] << 24) | (head[17] << 16) | (head[18] << 8) | head[19];
            int h = (head[20] << 24) | (head[21] << 16) | (head[22] << 8) | head[23];
            return new Vector2Int(w, h);
        }

        public static int Major(string version)
        {
            string first = (version ?? "").Split('.')[0];
            return int.TryParse(first, NumberStyles.Integer, CultureInfo.InvariantCulture, out int m) ? m : -1;
        }

        /// <summary>Collapses "." and ".." segments and backslashes: "Assets/dotwork/.." -> "Assets".</summary>
        public static string Norm(string path)
        {
            var parts = new List<string>();
            foreach (string p in path.Replace('\\', '/').Split('/'))
            {
                if (p == "" || p == ".")
                {
                    continue;
                }
                if (p == ".." && parts.Count > 0 && parts[parts.Count - 1] != "..")
                {
                    parts.RemoveAt(parts.Count - 1);
                }
                else
                {
                    parts.Add(p);
                }
            }
            return string.Join("/", parts);
        }

        public static string DirOf(string path)
        {
            int i = path.LastIndexOf('/');
            return i < 0 ? "" : path.Substring(0, i);
        }

        // ---- Typed accessors (missing or wrong type -> the default) ----------------------

        public static string Str(Dictionary<string, object> d, string key, string dflt = null)
        {
            return d != null && d.TryGetValue(key, out object v) && v is string s ? s : dflt;
        }

        public static double Num(Dictionary<string, object> d, string key, double dflt = 0)
        {
            return d != null && d.TryGetValue(key, out object v) && Json.IsNumber(v) ? Json.ToNumber(v) : dflt;
        }

        public static int Int(Dictionary<string, object> d, string key, int dflt = 0)
        {
            return (int)Math.Round(Num(d, key, dflt));
        }

        public static bool Bool(Dictionary<string, object> d, string key, bool dflt = false)
        {
            return d != null && d.TryGetValue(key, out object v) && v is bool b ? b : dflt;
        }

        public static bool Has(Dictionary<string, object> d, string key)
        {
            return d != null && d.TryGetValue(key, out object v) && v != null;
        }

        public static Dictionary<string, object> Obj(Dictionary<string, object> d, string key)
        {
            return d != null && d.TryGetValue(key, out object v) ? v as Dictionary<string, object> : null;
        }

        public static List<object> List(Dictionary<string, object> d, string key)
        {
            return d != null && d.TryGetValue(key, out object v) && v is List<object> l ? l : new List<object>();
        }

        public static IEnumerable<Dictionary<string, object>> Objs(Dictionary<string, object> d, string key)
        {
            foreach (object o in List(d, key))
            {
                if (o is Dictionary<string, object> od)
                {
                    yield return od;
                }
            }
        }

        /// <summary>A list of numbers as doubles (a rect, a point, a size); missing entries are 0.</summary>
        public static double[] Nums(object list, int count)
        {
            var r = new double[count];
            if (list is List<object> l)
            {
                for (int i = 0; i < count && i < l.Count; i++)
                {
                    r[i] = Json.IsNumber(l[i]) ? Json.ToNumber(l[i]) : 0;
                }
            }
            return r;
        }

        public static double[] Nums(Dictionary<string, object> d, string key, int count)
        {
            return Nums(d != null && d.TryGetValue(key, out object v) ? v : null, count);
        }
    }
}
